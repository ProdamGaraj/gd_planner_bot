"""Напоминания клиентам: накануне (с 10:00) и за 3 часа до встречи."""
import logging
from datetime import datetime, timedelta

from aiogram import Bot

from config import OFFICE_CONTACTS
from database.models import Booking, Contract
from database.session import SessionLocal
from locales.messages import LATE_WARNING, get_message
from services import booking_time
from services.booking_time import slot_start
from services.notify import safe_send
from services.users import get_user_language

log = logging.getLogger(__name__)

DAY_REMINDER_FROM_HOUR = 10  # не будим клиентов ночью
HOUR_REMINDER_BEFORE = timedelta(hours=3)


def due_reminders(session, now: datetime) -> list[tuple[Booking, str]]:
    """(встреча, 'day' | 'hour') — что пора отправить."""
    today = now.date()
    due = []
    if now.hour >= DAY_REMINDER_FROM_HOUR:
        for b in session.query(Booking).filter(
            Booking.date == today + timedelta(days=1),
            Booking.is_cancelled.is_(False),
            Booking.reminder_day_sent.is_(False),
        ):
            # Записался сегодня на завтра — только что получил подтверждение, не дублируем
            if b.created_at and b.created_at.date() >= today:
                continue
            due.append((b, "day"))
    for b in session.query(Booking).filter(
        Booking.date == today,
        Booking.is_cancelled.is_(False),
        Booking.reminder_hour_sent.is_(False),
    ):
        if now <= slot_start(b.date, b.time_slot) <= now + HOUR_REMINDER_BEFORE:
            due.append((b, "hour"))
    return due


async def send_reminders(bot: Bot) -> int:
    now = booking_time.now_tashkent()
    sent = 0
    with SessionLocal() as session:
        for booking, kind in due_reminders(session, now):
            contract: Contract = booking.contract
            chat_id = contract.telegram_id
            if chat_id:
                lang = get_user_language(session, chat_id)
                text = get_message(
                    f"reminder_{kind}", lang,
                    date=booking.date.strftime("%d.%m.%Y"),
                    time=booking.time_slot.strftime("%H:%M"),
                    address=OFFICE_CONTACTS[f"address_{lang}"],
                    late=LATE_WARNING[lang],
                )
                try:
                    if await safe_send(bot, chat_id, text):
                        sent += 1
                    # Заблокировал бота — тоже помечаем, иначе повтор каждые 2 минуты
                except Exception:
                    log.exception("Не удалось отправить напоминание по встрече #%s", booking.id)
                    continue  # сетевая ошибка — попробуем при следующей проверке
            # Без привязки отправить некому — помечаем, чтобы не проверять каждый раз
            if kind == "day":
                booking.reminder_day_sent = True
            else:
                booking.reminder_hour_sent = True
            session.commit()
    return sent
