import calendar
from datetime import date, time

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import Booking
from locales.messages import MONTHS, WEEKDAYS, get_message
from services.availability import DayStatus
from services.schedule import WINDOWS


class CalCb(CallbackData, prefix="cal"):
    # day — выбрать дату (value=YYYY-MM-DD), nav — листать (value=YYYY-MM),
    # full — дата занята, noop — пустая клетка/заголовок
    action: str
    value: str = ""


class SlotCb(CallbackData, prefix="slot"):
    # pick — выбрать (value=HHMM), taken — занято, back — к календарю
    action: str
    value: str = ""


class RescheduleCb(CallbackData, prefix="rsc"):
    # pick — выбрать встречу, locked — нельзя, yes/no — подтверждение переноса
    action: str
    booking_id: int = 0


TOPIC_SKIP = "topic:skip"
PHONE_SAVED = "phone:saved"
PHONE_NEW = "phone:new"


def _noop(text: str = " ") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=CalCb(action="noop").pack())


def calendar_kb(
    year: int, month: int, statuses: dict[date, DayStatus], lang: str, can_prev: bool, can_next: bool,
) -> InlineKeyboardMarkup:
    rows = [
        [_noop(f"{MONTHS[lang][month - 1]} {year}")],
        [_noop(d) for d in WEEKDAYS[lang]],
    ]
    for week in calendar.monthcalendar(year, month):
        row = []
        for day_num in week:
            if day_num == 0:
                row.append(_noop())
                continue
            day = date(year, month, day_num)
            status = statuses.get(day, DayStatus.OFF)
            if status is DayStatus.FREE:
                row.append(InlineKeyboardButton(
                    text=str(day_num), callback_data=CalCb(action="day", value=day.isoformat()).pack(),
                ))
            elif status is DayStatus.FULL:
                row.append(InlineKeyboardButton(text="❌", callback_data=CalCb(action="full").pack()))
            else:
                row.append(_noop("·"))
        rows.append(row)

    prev_y, prev_m = (year, month - 1) if month > 1 else (year - 1, 12)
    next_y, next_m = (year, month + 1) if month < 12 else (year + 1, 1)
    rows.append([
        InlineKeyboardButton(text="<<", callback_data=CalCb(action="nav", value=f"{prev_y}-{prev_m:02d}").pack())
        if can_prev else _noop(),
        InlineKeyboardButton(text=">>", callback_data=CalCb(action="nav", value=f"{next_y}-{next_m:02d}").pack())
        if can_next else _noop(),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def slots_kb(slots: dict[time, bool], lang: str) -> InlineKeyboardMarkup:
    """Слоты по окнам приёма (утро/вечер), по 3 в ряд."""
    rows = []
    for first, last in WINDOWS:
        window = [t for t in slots if first <= t <= last]
        for i in range(0, len(window), 3):
            row = []
            for t in window[i:i + 3]:
                label = t.strftime("%H:%M")
                if slots[t]:
                    row.append(InlineKeyboardButton(
                        text=f"✅ {label}", callback_data=SlotCb(action="pick", value=t.strftime("%H%M")).pack(),
                    ))
                else:
                    row.append(InlineKeyboardButton(text=f"❌ {label}", callback_data=SlotCb(action="taken").pack()))
            rows.append(row)
    rows.append([InlineKeyboardButton(
        text=get_message("btn_back_to_calendar", lang), callback_data=SlotCb(action="back").pack(),
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def topic_skip_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=get_message("btn_skip", lang), callback_data=TOPIC_SKIP),
    ]])


def phone_choice_kb(saved_phone: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_message("btn_use_saved_phone", lang, phone=saved_phone), callback_data=PHONE_SAVED)],
        [InlineKeyboardButton(text=get_message("btn_new_phone", lang), callback_data=PHONE_NEW)],
    ])


class CancelCb(CallbackData, prefix="cxl"):
    # pick — выбрать встречу, locked — отмена недоступна,
    # yes — подтвердить, no — оставить, back — закрыть список
    action: str
    booking_id: int = 0


def _label(b: Booking) -> str:
    return f"{b.date.strftime('%d.%m.%Y')} ⏰ {b.time_slot.strftime('%H:%M')}"


def cancel_list_kb(bookings: list[Booking], cancellable: dict[int, bool], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for b in bookings:
        if cancellable.get(b.id):
            builder.button(text=f"📅 {_label(b)}", callback_data=CancelCb(action="pick", booking_id=b.id))
        else:
            builder.button(text=f"🔒 {_label(b)}", callback_data=CancelCb(action="locked", booking_id=b.id))
    builder.button(text=get_message("btn_back", lang), callback_data=CancelCb(action="back"))
    builder.adjust(1)
    return builder.as_markup()


def reschedule_list_kb(bookings: list[Booking], allowed: dict[int, bool], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for b in bookings:
        if allowed.get(b.id):
            builder.button(text=f"📅 {_label(b)}", callback_data=RescheduleCb(action="pick", booking_id=b.id))
        else:
            builder.button(text=f"🔒 {_label(b)}", callback_data=RescheduleCb(action="locked", booking_id=b.id))
    builder.adjust(1)
    return builder.as_markup()


def reschedule_confirm_kb(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=get_message("btn_confirm_reschedule", lang), callback_data=RescheduleCb(action="yes"))
    builder.button(text=get_message("btn_keep", lang), callback_data=RescheduleCb(action="no"))
    builder.adjust(1)
    return builder.as_markup()


def cancel_confirm_kb(booking_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=get_message("btn_confirm_cancel", lang), callback_data=CancelCb(action="yes", booking_id=booking_id))
    builder.button(text=get_message("btn_keep", lang), callback_data=CancelCb(action="no", booking_id=booking_id))
    builder.adjust(1)
    return builder.as_markup()
