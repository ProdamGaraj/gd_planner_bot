from datetime import date, time, timedelta

import pytest

from services.schedule import (
    TIME_SLOTS, can_cancel, earliest_booking_date, is_working_day, min_booking_date,
)
from tests.conftest import tashkent

# Опорная неделя: 23.11.2026 — понедельник
MON, TUE, WED, THU, FRI, SAT, SUN = (date(2026, 11, 23) + timedelta(days=i) for i in range(7))
NEXT_MON, NEXT_TUE = date(2026, 11, 30), date(2026, 12, 1)


def test_reference_week():
    assert MON.weekday() == 0 and SUN.weekday() == 6


def test_time_slots():
    assert [s.strftime("%H:%M") for s in TIME_SLOTS] == [
        "10:00", "10:30", "11:00", "11:30", "12:00",
        "16:00", "16:30", "17:00", "17:30",
    ]


def test_working_day():
    assert is_working_day(MON)
    assert not is_working_day(SAT)
    assert not is_working_day(SUN)
    assert not is_working_day(TUE, {TUE})


@pytest.mark.parametrize("now, expected", [
    (tashkent(2026, 11, 23, 11, 59), TUE),       # Пн до 12:00 → Вт
    (tashkent(2026, 11, 23, 12, 0), WED),        # Пн после 12:00 → Ср
    (tashkent(2026, 11, 26, 9, 0), FRI),         # Чт до 12:00 → Пт
    (tashkent(2026, 11, 26, 15, 0), NEXT_MON),   # Чт после 12:00 → Пн
    (tashkent(2026, 11, 27, 9, 0), NEXT_MON),    # Пт → Пн
    (tashkent(2026, 11, 27, 18, 0), NEXT_MON),   # Пт вечер → Пн
    (tashkent(2026, 11, 28, 10, 0), NEXT_TUE),   # Сб → Вт
    (tashkent(2026, 11, 29, 23, 0), NEXT_TUE),   # Вс → Вт
])
def test_min_booking_date(now, expected):
    assert min_booking_date(now) == expected


def test_min_booking_date_skips_holidays():
    assert min_booking_date(tashkent(2026, 11, 23, 9), {TUE}) == WED
    assert min_booking_date(tashkent(2026, 11, 23, 13), {TUE}) == THU


def test_cooldown_extends_earliest_date():
    now = tashkent(2026, 11, 23, 9)  # без кулдауна — Вт
    assert earliest_booking_date(now) == TUE
    # Последняя встреча в Пн → +7 дней = следующий Пн
    assert earliest_booking_date(now, last_booking_date=MON, cooldown_days=7) == NEXT_MON
    # Кулдаун 0 — отключён
    assert earliest_booking_date(now, last_booking_date=MON, cooldown_days=0) == TUE
    # Старая встреча не сдвигает дату
    assert earliest_booking_date(now, last_booking_date=MON - timedelta(days=30), cooldown_days=7) == TUE


def test_can_cancel_working_day():
    slot = time(10, 0)
    # Пн до 12:00: Вт ещё можно, Пн (сегодня) — нет
    assert can_cancel(TUE, slot, tashkent(2026, 11, 23, 11))
    assert not can_cancel(MON, time(17, 0), tashkent(2026, 11, 23, 11))
    # Пн после 12:00: Вт уже нельзя, Ср можно
    assert not can_cancel(TUE, slot, tashkent(2026, 11, 23, 13))
    assert can_cancel(WED, slot, tashkent(2026, 11, 23, 13))


def test_can_cancel_on_holiday_until_start():
    holidays = {WED}
    assert can_cancel(WED, time(10, 0), tashkent(2026, 11, 25, 9, 59), holidays)
    assert not can_cancel(WED, time(10, 0), tashkent(2026, 11, 25, 10, 0), holidays)
