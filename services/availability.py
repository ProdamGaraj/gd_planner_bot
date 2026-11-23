"""Свободное время CEO: шаблон слотов минус праздники, блокировки админа и занятые слоты."""
import calendar
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from enum import Enum

from sqlalchemy.orm import Session

from config import BOOKING_HORIZON_DAYS
from database.models import BlockedSlot, Booking
from services import booking_time
from services.holidays import get_holiday_dates
from services.schedule import TIME_SLOTS, is_working_day


class DayStatus(str, Enum):
    OFF = "off"    # нельзя записаться: раньше минимальной даты, выходной, праздник, день закрыт
    FREE = "free"  # есть свободные слоты
    FULL = "full"  # рабочий день, но всё занято


def horizon_date(now: datetime | None = None) -> date:
    now = now or booking_time.now_tashkent()
    return now.date() + timedelta(days=BOOKING_HORIZON_DAYS)


def _closed_days(session: Session, start: date, end: date) -> set[date]:
    """Дни, целиком закрытые админом."""
    rows = session.query(BlockedSlot.date).filter(
        BlockedSlot.date.between(start, end), BlockedSlot.time_slot.is_(None),
    )
    return {r[0] for r in rows}


def _taken_slots(session: Session, start: date, end: date) -> dict[date, set[time]]:
    """Занятые записями и закрытые админом слоты по дням."""
    taken: dict[date, set[time]] = defaultdict(set)
    bookings = session.query(Booking.date, Booking.time_slot).filter(
        Booking.date.between(start, end), Booking.is_cancelled.is_(False),
    )
    blocks = session.query(BlockedSlot.date, BlockedSlot.time_slot).filter(
        BlockedSlot.date.between(start, end), BlockedSlot.time_slot.is_not(None),
    )
    for d, t in [*bookings, *blocks]:
        taken[d].add(t)
    return taken


def is_day_open(session: Session, day: date, earliest: date, now: datetime | None = None) -> bool:
    """День в окне записи, рабочий, не праздник и не закрыт целиком."""
    if not earliest <= day <= horizon_date(now):
        return False
    if not is_working_day(day, get_holiday_dates(session, day, day)):
        return False
    return day not in _closed_days(session, day, day)


def slot_map(session: Session, day: date) -> dict[time, bool]:
    """Все слоты дня: True — свободен."""
    if day in _closed_days(session, day, day):
        return {t: False for t in TIME_SLOTS}
    taken = _taken_slots(session, day, day)[day]
    return {t: t not in taken for t in TIME_SLOTS}


def month_status(
    session: Session, year: int, month: int, earliest: date, now: datetime | None = None,
) -> dict[date, DayStatus]:
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    horizon = horizon_date(now)
    holidays = get_holiday_dates(session, first, last)
    closed = _closed_days(session, first, last)
    taken = _taken_slots(session, first, last)

    result = {}
    day = first
    while day <= last:
        if not (earliest <= day <= horizon) or not is_working_day(day, holidays) or day in closed:
            result[day] = DayStatus.OFF
        elif len(taken[day] & set(TIME_SLOTS)) >= len(TIME_SLOTS):
            result[day] = DayStatus.FULL
        else:
            result[day] = DayStatus.FREE
        day += timedelta(days=1)
    return result
