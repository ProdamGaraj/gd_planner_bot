"""Управление расписанием CEO админом: закрытие/открытие слотов и дней."""
from dataclasses import dataclass
from datetime import date, time

from sqlalchemy.orm import Session

from database.models import BlockedSlot, Booking
from services.booking import (
    CANCELLED_BY_BLOCK, BookingInfo, active_bookings_on, booking_info, cancel_by_company,
)
from services.holidays import get_holiday_dates
from services.schedule import TIME_SLOTS, is_working_day


@dataclass
class SlotState:
    slot: time
    blocked: bool
    booking: Booking | None


@dataclass
class DayOverview:
    day: date
    working: bool          # рабочий день по шаблону (не выходной и не праздник)
    closed: bool           # закрыт админом целиком
    slots: list[SlotState]

    @property
    def bookings(self) -> list[Booking]:
        return [s.booking for s in self.slots if s.booking]


def day_overview(session: Session, day: date) -> DayOverview:
    blocks = session.query(BlockedSlot).filter(BlockedSlot.date == day).all()
    closed = any(b.time_slot is None for b in blocks)
    blocked_slots = {b.time_slot for b in blocks if b.time_slot is not None}
    booked = {b.time_slot: b for b in active_bookings_on(session, day)}
    return DayOverview(
        day=day,
        working=is_working_day(day, get_holiday_dates(session, day, day)),
        closed=closed,
        slots=[SlotState(t, t in blocked_slots, booked.get(t)) for t in TIME_SLOTS],
    )


def block_slot(session: Session, day: date, slot: time, admin_id: int) -> list[BookingInfo]:
    """Закрыть слот. Встречу на нём отменяет (уведомление — на вызывающем)."""
    if slot not in TIME_SLOTS:
        raise ValueError("Нет такого слота")
    exists = session.query(BlockedSlot).filter_by(date=day, time_slot=slot).first()
    if not exists:
        session.add(BlockedSlot(date=day, time_slot=slot, created_by=admin_id))
        session.commit()
    ids = [b.id for b in active_bookings_on(session, day, slot)]
    return cancel_by_company(session, ids, CANCELLED_BY_BLOCK)


def unblock_slot(session: Session, day: date, slot: time) -> None:
    session.query(BlockedSlot).filter_by(date=day, time_slot=slot).delete()
    session.commit()


def close_day(session: Session, day: date, admin_id: int) -> list[BookingInfo]:
    """Закрыть день целиком; все встречи дня отменяются."""
    if not session.query(BlockedSlot).filter(BlockedSlot.date == day, BlockedSlot.time_slot.is_(None)).first():
        session.add(BlockedSlot(date=day, time_slot=None, created_by=admin_id))
        session.commit()
    ids = [b.id for b in active_bookings_on(session, day)]
    return cancel_by_company(session, ids, CANCELLED_BY_BLOCK)


def open_day(session: Session, day: date) -> None:
    """Снять закрытие дня (закрытые отдельные слоты остаются)."""
    session.query(BlockedSlot).filter(BlockedSlot.date == day, BlockedSlot.time_slot.is_(None)).delete()
    session.commit()

