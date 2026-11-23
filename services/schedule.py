"""Правила расписания встреч с CEO: слоты, рабочие дни, минимальная дата, отмена.

Все функции чистые: текущее время и праздники передаются аргументами.
"""
from collections.abc import Collection
from datetime import date, datetime, time, timedelta

from services import booking_time
from services.booking_time import SLOT_DURATION, slot_start

# Окна приёма: (первое, последнее) время НАЧАЛА слота, включительно
WINDOWS: tuple[tuple[time, time], ...] = (
    (time(10, 0), time(12, 0)),
    (time(16, 0), time(17, 30)),
)

# После этого часа ближайший рабочий день пропускается
BOOKING_CUTOFF_HOUR = 12

NO_HOLIDAYS: frozenset[date] = frozenset()


def _build_slots() -> tuple[time, ...]:
    slots = []
    for first, last in WINDOWS:
        cur = datetime.combine(date.min, first)
        end = datetime.combine(date.min, last)
        while cur <= end:
            slots.append(cur.time())
            cur += SLOT_DURATION
    return tuple(slots)


TIME_SLOTS: tuple[time, ...] = _build_slots()


def is_working_day(day: date, holidays: Collection[date] = NO_HOLIDAYS) -> bool:
    return day.weekday() < 5 and day not in holidays


def next_working_day(day: date, holidays: Collection[date] = NO_HOLIDAYS) -> date:
    nxt = day + timedelta(days=1)
    while not is_working_day(nxt, holidays):
        nxt += timedelta(days=1)
    return nxt


def min_booking_date(now: datetime | None = None, holidays: Collection[date] = NO_HOLIDAYS) -> date:
    """Минимальная дата записи (правило dks_bot):

    - Пн–Чт до 12:00 — следующий рабочий день;
    - Пн–Чт после 12:00 — через один рабочий день;
    - Пт — следующий рабочий день (понедельник);
    - Сб/Вс — рабочий день после понедельника (вторник).
    """
    now = now or booking_time.now_tashkent()
    today = now.date()
    weekday = today.weekday()

    if weekday == 4:
        return next_working_day(today, holidays)
    if weekday >= 5:
        monday = today + timedelta(days=7 - weekday)
        return next_working_day(monday, holidays)

    first = next_working_day(today, holidays)
    if now.hour < BOOKING_CUTOFF_HOUR:
        return first
    return next_working_day(first, holidays)


def earliest_booking_date(
    now: datetime | None = None,
    holidays: Collection[date] = NO_HOLIDAYS,
    last_booking_date: date | None = None,
    cooldown_days: int = 0,
) -> date:
    """Минимальная дата с учётом кулдауна после последней записи клиента."""
    result = min_booking_date(now, holidays)
    if last_booking_date and cooldown_days > 0:
        result = max(result, last_booking_date + timedelta(days=cooldown_days))
    return result


def can_cancel(
    booking_date: date,
    time_slot: time,
    now: datetime | None = None,
    holidays: Collection[date] = NO_HOLIDAYS,
) -> bool:
    """Можно ли клиенту отменить/перенести встречу.

    Обычный день — не позже срока минимальной записи (1 рабочий день, после 12:00 — 2).
    Встреча, оказавшаяся на выходном/празднике, — до начала слота.
    """
    now = now or booking_time.now_tashkent()
    if not is_working_day(booking_date, holidays):
        return now < slot_start(booking_date, time_slot)
    return booking_date >= min_booking_date(now, holidays)
