"""Операции с записями к CEO. Единственное место, где меняется статус записи."""
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import Booking, Contract
from services import booking_time
from services.availability import is_day_open, slot_map
from services.booking_time import active_booking_filter, is_booking_past
from services.holidays import RULES_HORIZON_DAYS, get_holiday_dates, upcoming_holiday_dates
from services.schedule import can_cancel, earliest_booking_date
from services.settings import get_cooldown_days, get_no_show_ban_days

ATTENDANCE_CAME = "came"
ATTENDANCE_NO_SHOW = "no_show"
from services.users import build_tg_href

CANCELLED_BY_CLIENT = "client"
CANCELLED_BY_REBOOK = "rebook"
CANCELLED_BY_ADMIN = "admin"
CANCELLED_BY_HOLIDAY = "holiday"
CANCELLED_BY_BLOCK = "block"
COMPANY_REASONS = frozenset({CANCELLED_BY_ADMIN, CANCELLED_BY_HOLIDAY, CANCELLED_BY_BLOCK})


class CancelError(Exception):
    NOT_FOUND = "not_found"  # нет, чужая, уже отменена или прошла
    TOO_LATE = "too_late"    # срок отмены истёк

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class BookingInfo:
    """Снимок записи для сообщений — не зависит от сессии БД."""
    id: int
    date: date
    time_slot: time
    phone: str | None
    topic: str | None
    contract_num: str
    client_fio: str | None
    house_name: str
    apt_num: str | None
    entrance: str | None
    floor: int | None
    creator_tg_id: int | None       # кто создал запись
    creator_username: str | None
    owner_tg_id: int | None         # к кому сейчас привязан договор — ему шлём уведомления

    @property
    def date_str(self) -> str:
        return self.date.strftime("%d.%m.%Y")

    @property
    def time_str(self) -> str:
        return self.time_slot.strftime("%H:%M")


def booking_info(b: Booking) -> BookingInfo:
    c = b.contract
    return BookingInfo(
        id=b.id,
        date=b.date,
        time_slot=b.time_slot,
        phone=b.client_phone,
        topic=b.topic,
        contract_num=c.contract_num,
        client_fio=c.client_fio,
        house_name=c.house_name,
        apt_num=c.apt_num,
        entrance=c.entrance,
        floor=c.floor,
        creator_tg_id=b.user_telegram_id,
        # username хранится в договоре; берём его, только если привязка не менялась
        creator_username=c.username if c.telegram_id == b.user_telegram_id else None,
        owner_tg_id=c.telegram_id,
    )


# ===================== Запись =====================

class BookingError(Exception):
    CONTRACT_UNAVAILABLE = "contract_unavailable"  # нет договора или привязан к другому аккаунту
    HAS_ACTIVE = "has_active"                      # по договору уже есть будущая встреча
    DATE_UNAVAILABLE = "date_unavailable"          # дата вне окна / выходной / закрыта
    SLOT_TAKEN = "slot_taken"                      # слот занят или закрыт

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def normalize_contract_num(raw: str) -> str:
    return "".join(str(raw).split()).upper()


def find_contract(session: Session, raw_num: str) -> Contract | None:
    """Договор по введённому номеру. Пробелы и регистр не важны.

    Клиенты часто вводят номер без суффикса («13791» вместо «13791-GHP») или без
    дефиса («13791GHP»). Такой ввод принимаем, только если он однозначно
    указывает на один договор.
    """
    num = normalize_contract_num(raw_num)
    if not num:
        return None
    exact = session.query(Contract).filter(Contract.contract_num == num).first()
    if exact:
        return exact

    m = re.fullmatch(r"(\d+)([A-Z]+)", num)
    if m:  # без дефиса
        return session.query(Contract).filter(Contract.contract_num == f"{m[1]}-{m[2]}").first()
    if num.isdigit():  # без суффикса; только цифры — в LIKE нет спецсимволов
        matches = session.query(Contract).filter(Contract.contract_num.like(f"{num}-%")).limit(2).all()
        if len(matches) == 1:
            return matches[0]
    return None


def active_booking_for_contract(session: Session, contract_id: int, now: datetime | None = None) -> Booking | None:
    now = now or booking_time.now_tashkent()
    return (
        session.query(Booking)
        .filter(Booking.contract_id == contract_id, Booking.is_cancelled.is_(False), active_booking_filter(now))
        .order_by(Booking.date, Booking.time_slot)
        .first()
    )


def client_earliest_date(
    session: Session, contract_id: int, telegram_id: int, now: datetime | None = None,
    exclude_booking_id: int | None = None,
) -> date:
    """Минимальная дата записи с учётом правила 12:00, праздников и кулдауна.

    Кулдаун считается от последней неотменённой встречи этого аккаунта по договору.
    При переносе переносимая встреча не учитывается (exclude_booking_id).
    """
    now = now or booking_time.now_tashkent()
    query = session.query(Booking).filter(
        Booking.contract_id == contract_id,
        Booking.user_telegram_id == telegram_id,
        Booking.is_cancelled.is_(False),
    )
    if exclude_booking_id is not None:
        query = query.filter(Booking.id != exclude_booking_id)
    last = query.order_by(Booking.date.desc()).first()
    earliest = earliest_booking_date(
        now,
        upcoming_holiday_dates(session, now.date()),
        last.date if last else None,
        get_cooldown_days(session),
    )
    ban = no_show_ban(session, contract_id, now)
    return max(earliest, ban[1]) if ban else earliest


def no_show_ban(session: Session, contract_id: int, now: datetime | None = None) -> tuple[date, date] | None:
    """Действующий бан за неявку по договору: (дата пропущенной встречи, запись не раньше).

    Считается от последней неявки по договору — неважно, с какого аккаунта была запись.
    Если админ исправит отметку на «пришёл», бан снимается сам.
    """
    now = now or booking_time.now_tashkent()
    days = get_no_show_ban_days(session)
    if days <= 0:
        return None
    missed = (
        session.query(Booking.date)
        .filter(
            Booking.contract_id == contract_id,
            Booking.attendance == ATTENDANCE_NO_SHOW,
            Booking.is_cancelled.is_(False),
        )
        .order_by(Booking.date.desc())
        .first()
    )
    if missed is None:
        return None
    until = missed[0] + timedelta(days=days)
    return (missed[0], until) if until > now.date() else None


def create_booking(
    session: Session,
    *,
    contract_id: int,
    telegram_id: int,
    username: str | None,
    day: date,
    slot: time,
    phone: str,
    topic: str | None,
    now: datetime | None = None,
) -> BookingInfo:
    """Создать встречу. Все правила проверяются заново — данные из FSM не доверяем.

    При первой записи договор привязывается к аккаунту.
    """
    now = now or booking_time.now_tashkent()
    contract = session.get(Contract, contract_id)
    if contract is None:
        raise BookingError(BookingError.CONTRACT_UNAVAILABLE)
    if contract.telegram_id and contract.telegram_id != telegram_id:
        raise BookingError(BookingError.CONTRACT_UNAVAILABLE)
    if active_booking_for_contract(session, contract_id, now):
        raise BookingError(BookingError.HAS_ACTIVE)

    earliest = client_earliest_date(session, contract_id, telegram_id, now)
    if not is_day_open(session, day, earliest, now):
        raise BookingError(BookingError.DATE_UNAVAILABLE)
    if not slot_map(session, day).get(slot):
        raise BookingError(BookingError.SLOT_TAKEN)

    if contract.telegram_id is None:
        contract.telegram_id = telegram_id
    contract.username = username
    contract.href = build_tg_href(telegram_id, username)

    booking = Booking(
        contract_id=contract_id,
        user_telegram_id=telegram_id,
        date=day,
        time_slot=slot,
        client_phone=phone,
        topic=topic,
        created_at=now.replace(tzinfo=None),
    )
    session.add(booking)
    try:
        session.commit()
    except IntegrityError:
        # Кто-то занял слот между проверкой и записью (ux_bookings_active_slot)
        session.rollback()
        raise BookingError(BookingError.SLOT_TAKEN)
    return booking_info(booking)


# ===================== Отмена =====================

def client_active_bookings(session: Session, telegram_id: int, now: datetime | None = None) -> list[Booking]:
    """Будущие неотменённые встречи по договорам, привязанным к аккаунту."""
    now = now or booking_time.now_tashkent()
    return (
        session.query(Booking)
        .join(Contract, Booking.contract_id == Contract.id)
        .filter(
            Contract.telegram_id == telegram_id,
            Booking.is_cancelled.is_(False),
            active_booking_filter(now),
        )
        .order_by(Booking.date, Booking.time_slot)
        .all()
    )


def cancellable_map(session: Session, bookings: list[Booking], now: datetime | None = None) -> dict[int, bool]:
    """booking.id -> можно ли клиенту отменить её сейчас."""
    if not bookings:
        return {}
    now = now or booking_time.now_tashkent()
    today = now.date()
    until = max(max(b.date for b in bookings), today + timedelta(days=RULES_HORIZON_DAYS))
    holidays = get_holiday_dates(session, today, until)
    return {b.id: can_cancel(b.date, b.time_slot, now, holidays) for b in bookings}


def get_client_booking(session: Session, booking_id: int, telegram_id: int, now: datetime | None = None) -> Booking:
    """Активная встреча клиента, иначе CancelError(NOT_FOUND)."""
    now = now or booking_time.now_tashkent()
    b = session.get(Booking, booking_id)
    if (
        b is None
        or b.is_cancelled
        or b.contract.telegram_id != telegram_id
        or is_booking_past(b.date, b.time_slot, now)
    ):
        raise CancelError(CancelError.NOT_FOUND)
    return b


def _mark_cancelled(b: Booking, by: str, now: datetime) -> None:
    b.is_cancelled = True
    b.cancelled_by = by
    b.cancelled_at = now.replace(tzinfo=None)


def cancel_by_client(session: Session, booking_id: int, telegram_id: int, now: datetime | None = None) -> BookingInfo:
    """Клиент отменяет свою встречу (с проверкой срока отмены)."""
    now = now or booking_time.now_tashkent()
    b = get_client_booking(session, booking_id, telegram_id, now)
    if not cancellable_map(session, [b], now)[b.id]:
        raise CancelError(CancelError.TOO_LATE)
    _mark_cancelled(b, CANCELLED_BY_CLIENT, now)
    session.commit()
    return booking_info(b)


def cancel_by_company(
    session: Session, booking_ids: list[int], reason: str, now: datetime | None = None,
) -> list[BookingInfo]:
    """Отмена со стороны компании (CEO занят, праздник). Сроки отмены не действуют.

    Уже отменённые записи пропускаются. Возвращает отменённые сейчас.
    """
    if reason not in COMPANY_REASONS:
        raise ValueError(f"Неизвестная причина отмены: {reason}")
    if not booking_ids:
        return []
    now = now or booking_time.now_tashkent()
    bookings = (
        session.query(Booking)
        .filter(Booking.id.in_(booking_ids), Booking.is_cancelled.is_(False))
        .order_by(Booking.date, Booking.time_slot)
        .all()
    )
    for b in bookings:
        _mark_cancelled(b, reason, now)
    session.commit()
    return [booking_info(b) for b in bookings]


# ===================== Перенос =====================

def reschedule_booking(
    session: Session,
    *,
    booking_id: int,
    telegram_id: int,
    username: str | None,
    day: date,
    slot: time,
    now: datetime | None = None,
) -> tuple[BookingInfo, BookingInfo]:
    """Перенос встречи клиентом: отмена старой + новая запись в одной транзакции.

    Действует срок отмены; тема и телефон переносятся из старой встречи.
    Ошибки: CancelError (NOT_FOUND, TOO_LATE), BookingError (DATE_UNAVAILABLE, SLOT_TAKEN).
    """
    now = now or booking_time.now_tashkent()
    old = get_client_booking(session, booking_id, telegram_id, now)
    if not cancellable_map(session, [old], now)[old.id]:
        raise CancelError(CancelError.TOO_LATE)

    earliest = client_earliest_date(session, old.contract_id, telegram_id, now, exclude_booking_id=old.id)
    if not is_day_open(session, day, earliest, now):
        raise BookingError(BookingError.DATE_UNAVAILABLE)
    if not slot_map(session, day).get(slot):
        raise BookingError(BookingError.SLOT_TAKEN)

    old_info = booking_info(old)
    _mark_cancelled(old, CANCELLED_BY_REBOOK, now)
    old.contract.username = username
    old.contract.href = build_tg_href(telegram_id, username)
    new = Booking(
        contract_id=old.contract_id,
        user_telegram_id=telegram_id,
        date=day,
        time_slot=slot,
        client_phone=old.client_phone,
        topic=old.topic,
        created_at=now.replace(tzinfo=None),
    )
    session.add(new)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()  # старая встреча остаётся в силе
        raise BookingError(BookingError.SLOT_TAKEN)
    return old_info, booking_info(new)


# ===================== Для персонала =====================

def bookings_between(session: Session, start: date, end: date, now: datetime | None = None) -> list[Booking]:
    """Неотменённые и ещё не закончившиеся встречи за период (включительно)."""
    now = now or booking_time.now_tashkent()
    return (
        session.query(Booking)
        .filter(
            Booking.date.between(start, end),
            Booking.is_cancelled.is_(False),
            active_booking_filter(now),
        )
        .order_by(Booking.date, Booking.time_slot)
        .all()
    )


def active_bookings_on(
    session: Session, day: date, slot: time | None = None, now: datetime | None = None,
) -> list[Booking]:
    """Неотменённые и ещё не закончившиеся встречи дня (прошедшие отменять бессмысленно)."""
    now = now or booking_time.now_tashkent()
    query = session.query(Booking).filter(
        Booking.date == day, Booking.is_cancelled.is_(False), active_booking_filter(now),
    )
    if slot is not None:
        query = query.filter(Booking.time_slot == slot)
    return query.order_by(Booking.time_slot).all()
