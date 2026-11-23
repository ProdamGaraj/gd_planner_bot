"""Отметка явки клиента админами.

В момент начала встречи всем админам приходит сообщение с кнопками «Пришёл» /
«Не пришёл». Отмечает любой админ; после отметки сообщение обновляется у всех.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.orm import Session, object_session

from config import ADMIN_ID
from database.models import AttendancePrompt, Booking, Staff
from database.session import SessionLocal
from services import booking_time
from services.auth import ROLE_ADMIN
from services.booking import ATTENDANCE_CAME, ATTENDANCE_NO_SHOW, BookingInfo, booking_info, no_show_ban
from services.booking_time import slot_start
from services.notify import safe_send, staff_booking_text

log = logging.getLogger(__name__)

CAME = ATTENDANCE_CAME
NO_SHOW = ATTENDANCE_NO_SHOW
LABELS = {CAME: "✅ Пришёл", NO_SHOW: "❌ Не пришёл"}

# Если за столько часов после начала встречи никто не отметил явку — считаем, что клиент пришёл
AUTO_CONFIRM_HOURS = 12
AUTO_MARK_NAME = "автоматически"


class AttCb(CallbackData, prefix="att"):
    action: str          # came | no_show | fix
    booking_id: int
    force: bool = False  # True — исправление уже поставленной отметки


class AttendanceError(Exception):
    NOT_FOUND = "not_found"
    CANCELLED = "cancelled"
    NOT_STARTED = "not_started"
    ALREADY = "already"

    def __init__(self, code: str, booking: Booking | None = None):
        super().__init__(code)
        self.code = code
        self.booking = booking


def admin_recipients(session: Session) -> list[int]:
    ids = [r[0] for r in session.query(Staff.telegram_id).filter(Staff.role == ROLE_ADMIN)]
    if ADMIN_ID and ADMIN_ID not in ids:
        ids.insert(0, ADMIN_ID)
    return ids


# ===================== Тексты и кнопки =====================

def prompt_kb(booking_id: int, force: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=LABELS[CAME], callback_data=AttCb(action=CAME, booking_id=booking_id, force=force).pack()),
        InlineKeyboardButton(text=LABELS[NO_SHOW],
                             callback_data=AttCb(action=NO_SHOW, booking_id=booking_id, force=force).pack()),
    ]])


def fix_kb(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ Исправить", callback_data=AttCb(action="fix", booking_id=booking_id).pack()),
    ]])


def prompt_text(info: BookingInfo) -> str:
    return staff_booking_text("🕐 Встреча началась — отметьте явку", info)


def result_text(info: BookingInfo, b: Booking) -> str:
    """Вызывать, пока b привязан к сессии (для расчёта бана за неявку)."""
    who = b.attendance_by_name or str(b.attendance_by or "")
    at = b.attendance_at.strftime("%H:%M") if b.attendance_at else ""
    footer = None
    session = object_session(b)
    if b.attendance == NO_SHOW and session is not None:
        ban = no_show_ban(session, b.contract_id)
        if ban:
            footer = f"⛔ Бан за неявку: клиент сможет записаться не раньше {ban[1].strftime('%d.%m.%Y')}"
    if is_auto_marked(b):
        title = f"{LABELS[b.attendance]} — автоматически (за {AUTO_CONFIRM_HOURS} ч никто не отметил)"
    else:
        title = f"{LABELS[b.attendance]} — отметил(а) {who} в {at}"
    return staff_booking_text(title, info, footer=footer)


def is_auto_marked(b: Booking) -> bool:
    return b.attendance_by is None and b.attendance_by_name == AUTO_MARK_NAME


def cancelled_text(info: BookingInfo) -> str:
    return staff_booking_text("🚫 Встреча отменена — явка не отмечается", info)


# ===================== Логика =====================

def due_prompts(session: Session, now: datetime) -> list[Booking]:
    """Сегодняшние неотменённые встречи, которые уже начались и по которым запрос ещё не отправлен.

    Только сегодня: после долгого простоя бота не засыпаем админов старыми встречами.
    """
    candidates = session.query(Booking).filter(
        Booking.date == now.date(),
        Booking.is_cancelled.is_(False),
        Booking.attendance_prompted.is_(False),
        Booking.attendance.is_(None),
    ).order_by(Booking.time_slot)
    return [b for b in candidates if slot_start(b.date, b.time_slot) <= now]


def mark_attendance(
    session: Session, booking_id: int, status: str, admin_id: int, admin_name: str | None,
    force: bool = False, now: datetime | None = None,
) -> Booking:
    """Поставить отметку. Без force уже поставленную отметку не перезаписывает (ALREADY)."""
    if status not in (CAME, NO_SHOW):
        raise ValueError(status)
    now = now or booking_time.now_tashkent()
    b = session.get(Booking, booking_id)
    if b is None:
        raise AttendanceError(AttendanceError.NOT_FOUND)
    if b.is_cancelled:
        raise AttendanceError(AttendanceError.CANCELLED, b)
    if slot_start(b.date, b.time_slot) > now:
        raise AttendanceError(AttendanceError.NOT_STARTED, b)
    if b.attendance and not force:
        raise AttendanceError(AttendanceError.ALREADY, b)
    b.attendance = status
    b.attendance_by = admin_id
    b.attendance_by_name = admin_name
    b.attendance_at = now.replace(tzinfo=None)
    session.commit()
    return b


async def send_attendance_prompts(bot: Bot) -> int:
    """Задача планировщика: разослать запросы по начавшимся встречам. Возвращает число встреч."""
    now = booking_time.now_tashkent()
    with SessionLocal() as session:
        due = due_prompts(session, now)
        if not due:
            return 0
        admins = admin_recipients(session)
        for b in due:
            info = booking_info(b)
            for chat_id in admins:
                try:
                    msg = await bot.send_message(chat_id, prompt_text(info), parse_mode="HTML",
                                                 reply_markup=prompt_kb(b.id))
                    message_id = getattr(msg, "message_id", None)
                    if message_id:
                        session.add(AttendancePrompt(booking_id=b.id, chat_id=chat_id, message_id=message_id))
                except Exception:
                    log.exception("Не удалось отправить запрос явки по встрече #%s админу %s", b.id, chat_id)
                await asyncio.sleep(0.05)
            # Помечаем даже при сбое доставки — иначе повтор каждую минуту
            b.attendance_prompted = True
            session.commit()
        return len(due)


async def refresh_prompts(bot: Bot, booking_id: int, skip: tuple[int, int] | None = None) -> None:
    """Обновить у всех админов сообщения по встрече (после отметки или отмены).

    skip — (chat_id, message_id) сообщения, которое уже обновил сам обработчик.
    """
    with SessionLocal() as session:
        b = session.get(Booking, booking_id)
        if b is None:
            return
        info = booking_info(b)
        if b.is_cancelled:
            text, kb = cancelled_text(info), None
        elif b.attendance:
            text, kb = result_text(info, b), fix_kb(b.id)
        else:
            text, kb = prompt_text(info), prompt_kb(b.id)
        prompts = session.query(AttendancePrompt).filter_by(booking_id=booking_id).all()
        targets = [(p.chat_id, p.message_id) for p in prompts]
    for chat_id, message_id in targets:
        if (chat_id, message_id) == skip:
            continue
        try:
            await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id,
                                        parse_mode="HTML", reply_markup=kb)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                log.info("Не удалось обновить запрос явки %s/%s: %s", chat_id, message_id, e)
        except Exception:
            log.exception("Не удалось обновить запрос явки %s/%s", chat_id, message_id)


def due_auto_confirm(session: Session, now: datetime) -> list[Booking]:
    """Неотменённые встречи без отметки, с начала которых прошло AUTO_CONFIRM_HOURS часов и больше.

    Включая старые и те, по которым запрос не уходил (бот был выключен): молчание = пришёл.
    """
    deadline = now - timedelta(hours=AUTO_CONFIRM_HOURS)
    candidates = session.query(Booking).filter(
        Booking.date <= deadline.date(),
        Booking.is_cancelled.is_(False),
        Booking.attendance.is_(None),
    ).order_by(Booking.date, Booking.time_slot)
    return [b for b in candidates if slot_start(b.date, b.time_slot) <= deadline]


async def auto_confirm_attendance(bot: Bot) -> int:
    """Задача планировщика: проставить «пришёл» встречам, которые никто не отметил за 12 ч."""
    now = booking_time.now_tashkent()
    with SessionLocal() as session:
        due = due_auto_confirm(session, now)
        for b in due:
            b.attendance = CAME
            b.attendance_by = None
            b.attendance_by_name = AUTO_MARK_NAME
            b.attendance_at = now.replace(tzinfo=None)
        session.commit()
        ids = [b.id for b in due]
    if ids:
        log.info("Явка проставлена автоматически (нет отметки %s ч): встречи %s", AUTO_CONFIRM_HOURS, ids)
    for booking_id in ids:
        await refresh_prompts(bot, booking_id)
    return len(ids)


def attendance_label(b: Booking) -> str:
    label = LABELS.get(b.attendance, "не отмечено")
    return f"{label} (авто)" if is_auto_marked(b) else label


__all__ = [
    "AttCb", "AttendanceError", "CAME", "NO_SHOW", "LABELS", "admin_recipients", "attendance_label",
    "due_prompts", "fix_kb", "mark_attendance", "prompt_kb", "refresh_prompts", "result_text",
    "send_attendance_prompts", "safe_send",
]
