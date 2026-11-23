"""Панель персонала (админы и сотрудники): список встреч, отчёт. Админ может отменить встречу."""
from collections import defaultdict
from datetime import date, timedelta
from html import escape

from aiogram import Bot, F, Router, types
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from database.models import Booking
from database.session import SessionLocal
from handlers.utils import edit_message, send_long
from keyboards.reply import ADMIN_BUTTONS
from services import booking_time
from services.auth import IsStaffFilter, is_admin
from services.availability import horizon_date
from services.booking import CANCELLED_BY_ADMIN, BookingInfo, booking_info, bookings_between, cancel_by_company
from services.notify import notify_clients_company_cancel, notify_staff, spawn, staff_booking_text
from services.attendance import refresh_prompts
from services.reports import bookings_report
from services.users import format_tg_contact_html

router = Router()
router.message.filter(IsStaffFilter())
router.callback_query.filter(IsStaffFilter())

WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
PERIODS = {
    "today": "Сегодня",
    "tomorrow": "Завтра",
    "week": "Эта неделя",
    "next_week": "Следующая неделя",
    "all": "Все предстоящие",
}


class MeetCb(CallbackData, prefix="mt"):
    action: str     # period | cancel | yes | no
    value: str = ""


def _v(value) -> str:
    return escape(str(value)) if value not in (None, "") else "—"


def period_range(key: str, today: date) -> tuple[date, date]:
    monday = today - timedelta(days=today.weekday())
    return {
        "today": (today, today),
        "tomorrow": (today + timedelta(days=1), today + timedelta(days=1)),
        "week": (today, monday + timedelta(days=6)),
        "next_week": (monday + timedelta(days=7), monday + timedelta(days=13)),
        "all": (today, horizon_date()),
    }[key]


def meeting_block(info: BookingInfo) -> str:
    return (
        f"⏰ <b>{info.time_str}</b> — {_v(info.client_fio)}, кв. {_v(info.apt_num)} (дог. {_v(info.contract_num)})\n"
        f"    📞 {_v(info.phone)} · 💬 {format_tg_contact_html(info.creator_tg_id, info.creator_username)}\n"
        f"    📝 {_v(info.topic)}"
    )


def meetings_text(infos: list[BookingInfo], title: str) -> str:
    if not infos:
        return f"📋 <b>{escape(title)}</b>\n\nВстреч нет."
    by_day: dict[date, list[BookingInfo]] = defaultdict(list)
    for i in infos:
        by_day[i.date].append(i)
    parts = [f"📋 <b>{escape(title)}</b> — встреч: {len(infos)}"]
    for day, items in by_day.items():
        parts.append(f"<b>📅 {WEEKDAYS_RU[day.weekday()]}, {day.strftime('%d.%m.%Y')}</b>\n"
                     + "\n".join(meeting_block(i) for i in items))
    return "\n\n".join(parts)


def periods_kb() -> InlineKeyboardMarkup:
    keys = list(PERIODS)
    rows = [[InlineKeyboardButton(text=PERIODS[k], callback_data=MeetCb(action="period", value=k).pack())
             for k in keys[i:i + 2]] for i in range(0, len(keys), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_buttons_kb(infos: list[BookingInfo]) -> InlineKeyboardMarkup | None:
    if not infos:
        return None
    rows = [[InlineKeyboardButton(
        text=f"❌ {i.date.strftime('%d.%m')} {i.time_str} — {(i.client_fio or i.contract_num)[:25]}",
        callback_data=MeetCb(action="cancel", value=str(i.id)).pack(),
    )] for i in infos[:90]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ===================== Список встреч =====================

@router.message(F.text == ADMIN_BUTTONS["meetings"])
async def meetings_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("📋 За какой период показать встречи?", reply_markup=periods_kb())


@router.callback_query(MeetCb.filter(F.action == "period"))
async def meetings_period(callback: types.CallbackQuery, callback_data: MeetCb):
    start, end = period_range(callback_data.value, booking_time.now_tashkent().date())
    with SessionLocal() as session:
        infos = [booking_info(b) for b in bookings_between(session, start, end)]
    await callback.answer()
    title = f"{PERIODS[callback_data.value]} ({start.strftime('%d.%m')}–{end.strftime('%d.%m')})"
    kb = cancel_buttons_kb(infos) if is_admin(callback.from_user.id) else None
    await send_long(callback.message, meetings_text(infos, title), kb)


@router.callback_query(MeetCb.filter(F.action == "cancel"))
async def meeting_cancel_ask(callback: types.CallbackQuery, callback_data: MeetCb):
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    with SessionLocal() as session:
        b = session.get(Booking, int(callback_data.value))
        if b is None or b.is_cancelled:
            await callback.answer("Встреча уже отменена", show_alert=True)
            return
        info = booking_info(b)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отменить и уведомить клиента",
                              callback_data=MeetCb(action="yes", value=str(info.id)).pack())],
        [InlineKeyboardButton(text="↩️ Нет", callback_data=MeetCb(action="no").pack())],
    ])
    await callback.answer()
    await callback.message.answer(
        f"⚠️ <b>Отменить встречу?</b>\n\n📅 {info.date_str} {info.time_str}\n{meeting_block(info)}",
        parse_mode="HTML", reply_markup=kb,
    )


@router.callback_query(MeetCb.filter(F.action == "yes"))
async def meeting_cancel_confirmed(callback: types.CallbackQuery, callback_data: MeetCb, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    with SessionLocal() as session:
        infos = cancel_by_company(session, [int(callback_data.value)], CANCELLED_BY_ADMIN)
    await callback.answer()
    if not infos:
        await edit_message(callback, "Встреча уже была отменена.")
        return
    info = infos[0]
    delivered = await notify_clients_company_cancel(bot, infos, CANCELLED_BY_ADMIN)
    spawn(refresh_prompts(bot, info.id))  # если встреча уже шла — убрать кнопки явки у админов
    await edit_message(callback, f"✅ Встреча {info.date_str} {info.time_str} отменена. "
                                 + ("Клиент уведомлён." if delivered else "⚠️ Клиента уведомить не удалось."))
    admin = callback.from_user
    spawn(notify_staff(bot, staff_booking_text(
        "❌ Встреча отменена администратором", info,
        footer=f"Отменил: {admin.full_name} (@{admin.username})" if admin.username else f"Отменил: {admin.full_name}",
    )))


@router.callback_query(MeetCb.filter(F.action == "no"))
async def meeting_cancel_declined(callback: types.CallbackQuery):
    await callback.answer()
    await edit_message(callback, "↩️ Встреча остаётся в силе.")


# ===================== Отчёт =====================

@router.message(F.text == ADMIN_BUTTONS["report"])
async def report(message: types.Message, state: FSMContext):
    await state.clear()
    with SessionLocal() as session:
        data = bookings_report(session)
    stamp = booking_time.now_tashkent().strftime("%d.%m.%Y %H:%M")
    await message.answer_document(
        BufferedInputFile(data, filename="meetings_report.xlsx"),
        caption=f"📊 Отчёт по встречам на {stamp}",
    )
