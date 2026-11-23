"""Время по Ташкенту и правило «прошедшей» встречи.

Слот длится 30 минут; встреча считается прошедшей с момента окончания слота:
встреча на 10:00 становится прошедшей в 10:30 по Ташкенту.
Модуль — единственный источник истины для этого правила.
"""
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import and_, or_

from database.models import Booking

TASHKENT_TZ = timezone(timedelta(hours=5))
SLOT_DURATION = timedelta(minutes=30)


def now_tashkent() -> datetime:
    return datetime.now(TASHKENT_TZ)


def slot_start(booking_date: date, time_slot: time) -> datetime:
    return datetime.combine(booking_date, time_slot, tzinfo=TASHKENT_TZ)


def slot_end(booking_date: date, time_slot: time) -> datetime:
    return slot_start(booking_date, time_slot) + SLOT_DURATION


def is_booking_past(booking_date: date, time_slot: time, now: datetime | None = None) -> bool:
    return slot_end(booking_date, time_slot) <= (now or now_tashkent())


def active_booking_filter(now: datetime | None = None):
    """SQL-условие: слот ещё не закончился. Отмену проверяйте отдельно."""
    now = now or now_tashkent()
    today = now.date()
    cutoff = now - SLOT_DURATION
    if cutoff.date() < today:
        # Первые 30 минут суток — все сегодняшние слоты ещё впереди
        return Booking.date >= today
    return or_(
        Booking.date > today,
        and_(Booking.date == today, Booking.time_slot > cutoff.time().replace(tzinfo=None)),
    )
