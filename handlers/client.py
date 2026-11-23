"""Клиентские сценарии. Сейчас: отмена встречи.

Отмена работает без FSM: id встречи лежит в callback_data, а сервис заново
проверяет владельца и срок при каждом нажатии — старые кнопки безопасны.
"""
from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from config import OFFICE_CONTACTS
from handlers.booking import reschedule_start
from database.session import SessionLocal
from keyboards.inline import CancelCb, cancel_confirm_kb, cancel_list_kb
from keyboards.reply import client_button_variants, client_keyboard
from locales.messages import LATE_WARNING, get_message
from services.booking import (
    CancelError, booking_info, cancel_by_client, cancellable_map, client_active_bookings,
    get_client_booking,
)
from services.notify import notify_staff, spawn, staff_booking_text, tg_profile_kb
from services.users import get_user_language

router = Router()


def _lang(session, user: types.User) -> str:
    return get_user_language(session, user.id, user.language_code)


async def _edit(callback: types.CallbackQuery, text: str, kb=None) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def _show_cancel_error(callback: types.CallbackQuery, error: CancelError, lang: str) -> None:
    if error.code == CancelError.TOO_LATE:
        text = get_message("cancel_error_too_late", lang, phone=OFFICE_CONTACTS["phone"])
    else:
        text = get_message("cancel_error_not_found", lang)
    await _edit(callback, text)
    await callback.answer()


@router.message(F.text.in_(client_button_variants("cancel")))
async def cancel_start(message: types.Message, state: FSMContext):
    await state.clear()
    with SessionLocal() as session:
        lang = _lang(session, message.from_user)
        bookings = client_active_bookings(session, message.from_user.id)
        if not bookings:
            await message.answer(get_message("no_meetings_to_cancel", lang), reply_markup=client_keyboard(lang))
            return

        allowed = cancellable_map(session, bookings)
        rule = get_message("cancel_rule", lang)
        if not any(allowed.values()):
            await message.answer(
                get_message("all_meetings_locked", lang, rule=rule, phone=OFFICE_CONTACTS["phone"]),
                reply_markup=client_keyboard(lang),
            )
            return

        await message.answer(
            get_message("select_meeting_to_cancel", lang, rule=rule),
            reply_markup=cancel_list_kb(bookings, allowed, lang),
        )


@router.callback_query(CancelCb.filter(F.action == "locked"))
async def cancel_locked(callback: types.CallbackQuery):
    with SessionLocal() as session:
        lang = _lang(session, callback.from_user)
    await callback.answer(get_message("cancel_locked_alert", lang), show_alert=True)


@router.callback_query(CancelCb.filter(F.action == "pick"))
async def cancel_pick(callback: types.CallbackQuery, callback_data: CancelCb):
    with SessionLocal() as session:
        lang = _lang(session, callback.from_user)
        try:
            booking = get_client_booking(session, callback_data.booking_id, callback.from_user.id)
            if not cancellable_map(session, [booking])[booking.id]:
                raise CancelError(CancelError.TOO_LATE)
            info = booking_info(booking)
        except CancelError as e:
            await _show_cancel_error(callback, e, lang)
            return

    await _edit(
        callback,
        get_message("confirm_cancel", lang, date=info.date_str, time=info.time_str, contract=info.contract_num),
        cancel_confirm_kb(info.id, lang),
    )
    await callback.answer()


@router.callback_query(CancelCb.filter(F.action == "yes"))
async def cancel_confirmed(callback: types.CallbackQuery, callback_data: CancelCb, bot: Bot):
    with SessionLocal() as session:
        lang = _lang(session, callback.from_user)
        try:
            info = cancel_by_client(session, callback_data.booking_id, callback.from_user.id)
        except CancelError as e:
            await _show_cancel_error(callback, e, lang)
            return

    await _edit(callback, get_message("meeting_cancelled", lang, date=info.date_str, time=info.time_str))
    await callback.answer()
    spawn(notify_staff(
        bot,
        staff_booking_text("❌ Встреча отменена клиентом", info),
        tg_profile_kb(info.creator_tg_id, info.creator_username),
    ))


@router.callback_query(CancelCb.filter(F.action.in_({"no", "back"})))
async def cancel_aborted(callback: types.CallbackQuery):
    with SessionLocal() as session:
        lang = _lang(session, callback.from_user)
    await _edit(callback, get_message("cancel_aborted", lang))
    await callback.answer()


# ---------- Мои встречи ----------

@router.message(F.text.in_(client_button_variants("my")))
async def my_meetings(message: types.Message, state: FSMContext):
    await state.clear()
    with SessionLocal() as session:
        lang = _lang(session, message.from_user)
        bookings = client_active_bookings(session, message.from_user.id)
        if not bookings:
            await message.answer(get_message("no_meetings", lang), reply_markup=client_keyboard(lang))
            return
        items = [
            get_message("my_meeting_item", lang, date=i.date_str, time=i.time_str,
                        contract=i.contract_num, topic=i.topic or "—")
            for i in map(booking_info, bookings)
        ]
    text = "\n\n".join([
        get_message("my_meetings_header", lang),
        *items,
        get_message("my_meetings_footer", lang, address=OFFICE_CONTACTS[f"address_{lang}"], late=LATE_WARNING[lang]),
    ])
    await message.answer(text, reply_markup=client_keyboard(lang))


# Перенос — сценарий в handlers/booking.py; кнопку регистрируем здесь, чтобы она
# срабатывала и посреди записи (клиентский роутер подключён раньше роутера записи)
router.message.register(reschedule_start, F.text.in_(client_button_variants("reschedule")))
