"""Запись на встречу с CEO: договор → дата → время → тема → телефон → подтверждение.

Данные шага хранятся в FSM, но при создании записи сервис проверяет всё заново.
"""
from datetime import date, datetime

from aiogram import Bot, F, Router, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from sqlalchemy.orm import Session

from config import OFFICE_CONTACTS, TOPIC_MAX_LENGTH
from database.session import SessionLocal
from handlers.states import BookingSteps
from handlers.utils import edit_message, user_lang
from keyboards.inline import (
    PHONE_NEW, PHONE_SAVED, TOPIC_SKIP, CalCb, RescheduleCb, SlotCb, calendar_kb, phone_choice_kb,
    reschedule_confirm_kb, reschedule_list_kb, slots_kb, topic_skip_kb,
)
from keyboards.reply import client_button_variants, client_keyboard, phone_request_keyboard
from locales.messages import LATE_WARNING, get_message
from services.availability import horizon_date, is_day_open, month_status, slot_map
from services.booking import (
    BookingError, CancelError, active_booking_for_contract, cancellable_map, client_active_bookings,
    client_earliest_date, create_booking, find_contract, get_client_booking, no_show_ban, reschedule_booking,
)
from services.notify import notify_staff, spawn, staff_booking_text, tg_profile_kb
from services.phone import validate_phone
from services.users import get_user_phone, set_user_phone, toggle_language

router = Router()

DATE_FMT = "%d.%m.%Y"
MODE_BOOK = "book"
MODE_RESCHEDULE = "reschedule"


# ===================== Представления шагов =====================

def _ym(d: date) -> tuple[int, int]:
    return d.year, d.month


def calendar_view(session: Session, data: dict, lang: str, ym: tuple[int, int] | None = None):
    """(текст, клавиатура, показанный месяц). Месяц ограничен окном записи."""
    earliest = date.fromisoformat(data["earliest"])
    first, last = _ym(earliest), _ym(horizon_date())
    if ym is None:
        y, m = (int(x) for x in data.get("month", f"{earliest.year}-{earliest.month}").split("-"))
        ym = (y, m)
    ym = max(first, min(ym, last))
    statuses = month_status(session, ym[0], ym[1], earliest)
    kb = calendar_kb(ym[0], ym[1], statuses, lang, can_prev=ym > first, can_next=ym < last)
    text = get_message("select_date", lang, date=earliest.strftime(DATE_FMT))
    if data.get("mode") == MODE_RESCHEDULE:
        text = get_message("reschedule_header", lang, date=data["old_date"], time=data["old_time"]) + "\n\n" + text
    return text, kb, ym


def reschedule_confirm_text(data: dict, lang: str) -> str:
    return get_message(
        "confirm_reschedule", lang,
        old_date=data["old_date"], old_time=data["old_time"],
        new_date=date.fromisoformat(data["day"]).strftime(DATE_FMT),
        new_time=datetime.strptime(data["slot"], "%H%M").strftime("%H:%M"),
    )


def slots_view(session: Session, day: date, lang: str):
    text = get_message("select_time", lang, date=day.strftime(DATE_FMT), late=LATE_WARNING[lang])
    return text, slots_kb(slot_map(session, day), lang)


async def ask_phone(message: types.Message, user_id: int, lang: str) -> None:
    with SessionLocal() as session:
        saved = get_user_phone(session, user_id)
    if saved:
        await message.answer(get_message("phone_choice", lang), reply_markup=phone_choice_kb(saved, lang))
    else:
        await message.answer(get_message("enter_phone", lang), reply_markup=phone_request_keyboard(lang))


async def render_step(message: types.Message, state: FSMContext, user: types.User, lang: str) -> None:
    """Показать текущий шаг заново (после смены языка)."""
    current = await state.get_state()
    data = await state.get_data()
    if current == BookingSteps.entering_contract.state:
        await message.answer(get_message("enter_contract", lang), reply_markup=client_keyboard(lang))
    elif current == BookingSteps.selecting_date.state:
        with SessionLocal() as session:
            text, kb, _ = calendar_view(session, data, lang)
        await message.answer(text, reply_markup=kb)
    elif current == BookingSteps.selecting_time.state:
        with SessionLocal() as session:
            text, kb = slots_view(session, date.fromisoformat(data["day"]), lang)
        await message.answer(text, reply_markup=kb)
    elif current == BookingSteps.entering_topic.state:
        await message.answer(get_message("enter_topic", lang, max=TOPIC_MAX_LENGTH), reply_markup=topic_skip_kb(lang))
    elif current == BookingSteps.entering_phone.state:
        await ask_phone(message, user.id, lang)
    elif current == BookingSteps.confirming_reschedule.state:
        await message.answer(reschedule_confirm_text(data, lang), reply_markup=reschedule_confirm_kb(lang))


# ===================== Старт и смена языка =====================

@router.message(F.text.in_(client_button_variants("book")))
async def book_start(message: types.Message, state: FSMContext):
    await state.clear()
    with SessionLocal() as session:
        lang = user_lang(session, message.from_user)
    await state.set_state(BookingSteps.entering_contract)
    await message.answer(get_message("enter_contract", lang), reply_markup=client_keyboard(lang))


@router.message(F.text.in_(client_button_variants("language")), StateFilter(BookingSteps))
async def language_toggle_in_flow(message: types.Message, state: FSMContext):
    with SessionLocal() as session:
        lang = toggle_language(session, message.from_user.id)
    await message.answer(get_message("language_changed", lang), reply_markup=client_keyboard(lang))
    await render_step(message, state, message.from_user, lang)


# ===================== Договор =====================

@router.message(BookingSteps.entering_contract, F.text)
async def contract_entered(message: types.Message, state: FSMContext):
    user = message.from_user
    with SessionLocal() as session:
        lang = user_lang(session, user)
        contract = find_contract(session, message.text)
        if contract is None:
            await message.answer(get_message("contract_not_found", lang))
            return
        if contract.telegram_id and contract.telegram_id != user.id:
            await message.answer(get_message("contract_unavailable", lang, phone=OFFICE_CONTACTS["phone"]))
            return

        active = active_booking_for_contract(session, contract.id)
        if active:
            await state.clear()
            await message.answer(
                get_message("has_active_meeting", lang,
                            date=active.date.strftime(DATE_FMT), time=active.time_slot.strftime("%H:%M")),
                reply_markup=client_keyboard(lang),
            )
            return

        earliest = client_earliest_date(session, contract.id, user.id)
        if earliest > horizon_date():
            await state.clear()
            await message.answer(get_message("no_dates_available", lang), reply_markup=client_keyboard(lang))
            return

        data = {"mode": MODE_BOOK, "contract_id": contract.id, "earliest": earliest.isoformat(),
                "month": f"{earliest.year}-{earliest.month}"}
        await state.update_data(**data)
        await state.set_state(BookingSteps.selecting_date)
        text, kb, _ = calendar_view(session, data, lang)
        fio = contract.client_fio or contract.contract_num
        ban = no_show_ban(session, contract.id)

    await message.answer(get_message("contract_confirmed", lang, fio=fio))
    if ban:
        await message.answer(get_message("no_show_ban", lang, missed=ban[0].strftime(DATE_FMT),
                                         until=ban[1].strftime(DATE_FMT)))
    await message.answer(text, reply_markup=kb)


@router.message(BookingSteps.entering_contract)
async def contract_not_text(message: types.Message):
    with SessionLocal() as session:
        lang = user_lang(session, message.from_user)
    await message.answer(get_message("enter_contract", lang))


# ===================== Календарь =====================

@router.callback_query(CalCb.filter(F.action == "noop"))
async def calendar_noop(callback: types.CallbackQuery):
    await callback.answer()


@router.callback_query(BookingSteps.selecting_date, CalCb.filter(F.action == "full"))
async def calendar_full(callback: types.CallbackQuery):
    with SessionLocal() as session:
        lang = user_lang(session, callback.from_user)
    await callback.answer(get_message("date_full_alert", lang), show_alert=True)


@router.callback_query(BookingSteps.selecting_date, CalCb.filter(F.action == "nav"))
async def calendar_nav(callback: types.CallbackQuery, callback_data: CalCb, state: FSMContext):
    y, m = (int(x) for x in callback_data.value.split("-"))
    data = await state.get_data()
    with SessionLocal() as session:
        lang = user_lang(session, callback.from_user)
        text, kb, ym = calendar_view(session, data, lang, (y, m))
    await state.update_data(month=f"{ym[0]}-{ym[1]}")
    await edit_message(callback, text, kb)
    await callback.answer()


@router.callback_query(BookingSteps.selecting_date, CalCb.filter(F.action == "day"))
async def calendar_day(callback: types.CallbackQuery, callback_data: CalCb, state: FSMContext):
    day = date.fromisoformat(callback_data.value)
    data = await state.get_data()
    with SessionLocal() as session:
        lang = user_lang(session, callback.from_user)
        earliest = date.fromisoformat(data["earliest"])
        free = is_day_open(session, day, earliest) and any(slot_map(session, day).values())
        if not free:
            # Дату заняли или закрыли, пока клиент смотрел календарь
            text, kb, _ = calendar_view(session, data, lang, _ym(day))
            await edit_message(callback, text, kb)
            await callback.answer(get_message("date_unavailable_alert", lang), show_alert=True)
            return
        text, kb = slots_view(session, day, lang)

    await state.update_data(day=day.isoformat(), month=f"{day.year}-{day.month}")
    await state.set_state(BookingSteps.selecting_time)
    await edit_message(callback, text, kb)
    await callback.answer()


# ===================== Время =====================

@router.callback_query(BookingSteps.selecting_time, SlotCb.filter(F.action == "taken"))
async def slot_taken(callback: types.CallbackQuery):
    with SessionLocal() as session:
        lang = user_lang(session, callback.from_user)
    await callback.answer(get_message("slot_taken_alert", lang), show_alert=True)


@router.callback_query(BookingSteps.selecting_time, SlotCb.filter(F.action == "back"))
async def slot_back(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    with SessionLocal() as session:
        lang = user_lang(session, callback.from_user)
        text, kb, _ = calendar_view(session, data, lang)
    await state.set_state(BookingSteps.selecting_date)
    await edit_message(callback, text, kb)
    await callback.answer()


@router.callback_query(BookingSteps.selecting_time, SlotCb.filter(F.action == "pick"))
async def slot_pick(callback: types.CallbackQuery, callback_data: SlotCb, state: FSMContext):
    slot = datetime.strptime(callback_data.value, "%H%M").time()
    data = await state.get_data()
    day = date.fromisoformat(data["day"])
    with SessionLocal() as session:
        lang = user_lang(session, callback.from_user)
        if not slot_map(session, day).get(slot):
            text, kb = slots_view(session, day, lang)
            await edit_message(callback, text, kb)
            await callback.answer(get_message("slot_taken_alert", lang), show_alert=True)
            return

    await state.update_data(slot=callback_data.value)
    if data.get("mode") == MODE_RESCHEDULE:
        await state.set_state(BookingSteps.confirming_reschedule)
        await edit_message(callback, reschedule_confirm_text(await state.get_data(), lang),
                           reschedule_confirm_kb(lang))
        await callback.answer()
        return
    await state.set_state(BookingSteps.entering_topic)
    await edit_message(callback, get_message("slot_selected", lang, date=day.strftime(DATE_FMT),
                                             time=slot.strftime("%H:%M")))
    await callback.answer()
    await callback.message.answer(
        get_message("enter_topic", lang, max=TOPIC_MAX_LENGTH), reply_markup=topic_skip_kb(lang),
    )


# ===================== Тема =====================

@router.message(BookingSteps.entering_topic, F.text)
async def topic_entered(message: types.Message, state: FSMContext):
    with SessionLocal() as session:
        lang = user_lang(session, message.from_user)
    topic = message.text.strip()
    if len(topic) > TOPIC_MAX_LENGTH:
        await message.answer(get_message("topic_too_long", lang, length=len(topic), max=TOPIC_MAX_LENGTH))
        return
    await state.update_data(topic=topic or None)
    await state.set_state(BookingSteps.entering_phone)
    await ask_phone(message, message.from_user.id, lang)


@router.callback_query(BookingSteps.entering_topic, F.data == TOPIC_SKIP)
async def topic_skipped(callback: types.CallbackQuery, state: FSMContext):
    with SessionLocal() as session:
        lang = user_lang(session, callback.from_user)
    await state.update_data(topic=None)
    await state.set_state(BookingSteps.entering_phone)
    await edit_message(callback, get_message("topic_skipped", lang))
    await callback.answer()
    await ask_phone(callback.message, callback.from_user.id, lang)


@router.message(BookingSteps.entering_topic)
async def topic_not_text(message: types.Message):
    with SessionLocal() as session:
        lang = user_lang(session, message.from_user)
    await message.answer(get_message("topic_text_only", lang))


# ===================== Телефон и создание записи =====================

async def finish_booking(
    target: types.Message, user: types.User, state: FSMContext, bot: Bot, phone: str, lang: str,
) -> None:
    data = await state.get_data()
    day = date.fromisoformat(data["day"])
    slot = datetime.strptime(data["slot"], "%H%M").time()

    with SessionLocal() as session:
        try:
            info = create_booking(
                session,
                contract_id=data["contract_id"],
                telegram_id=user.id,
                username=user.username,
                day=day,
                slot=slot,
                phone=phone,
                topic=data.get("topic"),
            )
        except BookingError as e:
            await _booking_failed(target, state, session, e, data, day, lang)
            return
        set_user_phone(session, user.id, phone)

    await state.clear()
    await target.answer(
        get_message(
            "booking_confirmed", lang,
            date=info.date_str, time=info.time_str,
            address=OFFICE_CONTACTS[f"address_{lang}"],
            contract=info.contract_num, fio=info.client_fio or "—",
            phone=info.phone, topic=info.topic or "—",
            late=LATE_WARNING[lang],
        ),
        reply_markup=client_keyboard(lang),
    )
    await target.answer_location(latitude=OFFICE_CONTACTS["latitude"], longitude=OFFICE_CONTACTS["longitude"])
    spawn(notify_staff(
        bot,
        staff_booking_text("🔔 Новая встреча с CEO", info),
        tg_profile_kb(info.creator_tg_id, info.creator_username),
    ))


async def _booking_failed(target, state, session, error: BookingError, data, day, lang) -> None:
    if error.code == BookingError.SLOT_TAKEN:
        await state.set_state(BookingSteps.selecting_time)
        text, kb = slots_view(session, day, lang)
        await target.answer(get_message("error_slot_taken", lang), reply_markup=client_keyboard(lang))
        await target.answer(text, reply_markup=kb)
    elif error.code == BookingError.DATE_UNAVAILABLE:
        await state.set_state(BookingSteps.selecting_date)
        text, kb, _ = calendar_view(session, data, lang, _ym(day))
        await target.answer(get_message("error_date_unavailable", lang), reply_markup=client_keyboard(lang))
        await target.answer(text, reply_markup=kb)
    elif error.code == BookingError.HAS_ACTIVE:
        await state.clear()
        active = active_booking_for_contract(session, data["contract_id"])
        text = (
            get_message("has_active_meeting", lang,
                        date=active.date.strftime(DATE_FMT), time=active.time_slot.strftime("%H:%M"))
            if active else get_message("cancel_error_not_found", lang)
        )
        await target.answer(text, reply_markup=client_keyboard(lang))
    else:
        await state.clear()
        await target.answer(
            get_message("contract_unavailable", lang, phone=OFFICE_CONTACTS["phone"]),
            reply_markup=client_keyboard(lang),
        )


@router.callback_query(BookingSteps.entering_phone, F.data == PHONE_SAVED)
async def phone_saved(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    with SessionLocal() as session:
        lang = user_lang(session, callback.from_user)
        saved = get_user_phone(session, callback.from_user.id)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    if not saved:
        await callback.message.answer(get_message("enter_phone", lang), reply_markup=phone_request_keyboard(lang))
        return
    await finish_booking(callback.message, callback.from_user, state, bot, saved, lang)


@router.callback_query(BookingSteps.entering_phone, F.data == PHONE_NEW)
async def phone_new(callback: types.CallbackQuery):
    with SessionLocal() as session:
        lang = user_lang(session, callback.from_user)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(get_message("enter_phone", lang), reply_markup=phone_request_keyboard(lang))


@router.message(BookingSteps.entering_phone, F.contact | F.text)
async def phone_entered(message: types.Message, state: FSMContext, bot: Bot):
    with SessionLocal() as session:
        lang = user_lang(session, message.from_user)
    raw = message.contact.phone_number if message.contact else message.text
    ok, phone = validate_phone(raw)
    if not ok:
        await message.answer(get_message("invalid_phone", lang), reply_markup=phone_request_keyboard(lang))
        return
    await finish_booking(message, message.from_user, state, bot, phone, lang)


# ===================== Перенос встречи =====================

async def _start_reschedule(target: types.Message, edit_cb: types.CallbackQuery | None, state: FSMContext,
                            booking, user: types.User, lang: str, session: Session) -> None:
    """Открыть календарь для переноса выбранной встречи."""
    earliest = client_earliest_date(session, booking.contract_id, user.id, exclude_booking_id=booking.id)
    data = {
        "mode": MODE_RESCHEDULE,
        "booking_id": booking.id,
        "contract_id": booking.contract_id,
        "earliest": earliest.isoformat(),
        "month": f"{earliest.year}-{earliest.month}",
        "old_date": booking.date.strftime(DATE_FMT),
        "old_time": booking.time_slot.strftime("%H:%M"),
    }
    await state.set_data(data)
    await state.set_state(BookingSteps.selecting_date)
    text, kb, _ = calendar_view(session, data, lang)
    if edit_cb:
        await edit_message(edit_cb, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


async def reschedule_start(message: types.Message, state: FSMContext):
    """Регистрируется в handlers/client.py — раньше обработчиков шагов записи."""
    await state.clear()
    user = message.from_user
    with SessionLocal() as session:
        lang = user_lang(session, user)
        bookings = client_active_bookings(session, user.id)
        if not bookings:
            await message.answer(get_message("no_meetings_to_reschedule", lang), reply_markup=client_keyboard(lang))
            return
        allowed = cancellable_map(session, bookings)
        rule = get_message("cancel_rule", lang)
        if not any(allowed.values()):
            await message.answer(
                get_message("all_meetings_locked_reschedule", lang, rule=rule, phone=OFFICE_CONTACTS["phone"]),
                reply_markup=client_keyboard(lang),
            )
            return
        if len(bookings) == 1:
            await _start_reschedule(message, None, state, bookings[0], user, lang, session)
            return
        await message.answer(
            get_message("select_meeting_to_reschedule", lang, rule=rule),
            reply_markup=reschedule_list_kb(bookings, allowed, lang),
        )


@router.callback_query(RescheduleCb.filter(F.action == "locked"))
async def reschedule_locked(callback: types.CallbackQuery):
    with SessionLocal() as session:
        lang = user_lang(session, callback.from_user)
    await callback.answer(get_message("reschedule_locked_alert", lang), show_alert=True)


@router.callback_query(RescheduleCb.filter(F.action == "pick"))
async def reschedule_pick(callback: types.CallbackQuery, callback_data: RescheduleCb, state: FSMContext):
    user = callback.from_user
    with SessionLocal() as session:
        lang = user_lang(session, user)
        try:
            booking = get_client_booking(session, callback_data.booking_id, user.id)
        except CancelError:
            await edit_message(callback, get_message("cancel_error_not_found", lang))
            await callback.answer()
            return
        if not cancellable_map(session, [booking])[booking.id]:
            await edit_message(callback, get_message("reschedule_error_too_late", lang, phone=OFFICE_CONTACTS["phone"]))
            await callback.answer()
            return
        await _start_reschedule(callback.message, callback, state, booking, user, lang, session)
    await callback.answer()


@router.callback_query(BookingSteps.confirming_reschedule, RescheduleCb.filter(F.action == "no"))
async def reschedule_declined(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    with SessionLocal() as session:
        lang = user_lang(session, callback.from_user)
    await edit_message(callback, get_message("cancel_aborted", lang))
    await callback.answer()


@router.callback_query(BookingSteps.confirming_reschedule, RescheduleCb.filter(F.action == "yes"))
async def reschedule_confirmed(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    user = callback.from_user
    data = await state.get_data()
    day = date.fromisoformat(data["day"])
    slot = datetime.strptime(data["slot"], "%H%M").time()

    with SessionLocal() as session:
        lang = user_lang(session, user)
        try:
            old, new = reschedule_booking(
                session, booking_id=data["booking_id"], telegram_id=user.id, username=user.username,
                day=day, slot=slot,
            )
        except CancelError as e:
            await state.clear()
            key = "reschedule_error_too_late" if e.code == CancelError.TOO_LATE else "cancel_error_not_found"
            await edit_message(callback, get_message(key, lang, phone=OFFICE_CONTACTS["phone"]))
            await callback.answer()
            return
        except BookingError as e:
            await callback.answer()
            if e.code == BookingError.SLOT_TAKEN:
                await state.set_state(BookingSteps.selecting_time)
                text, kb = slots_view(session, day, lang)
                await edit_message(callback, get_message("error_slot_taken", lang) + "\n\n" + text, kb)
            else:
                await state.set_state(BookingSteps.selecting_date)
                text, kb, _ = calendar_view(session, data, lang, _ym(day))
                await edit_message(callback, get_message("error_date_unavailable", lang) + "\n\n" + text, kb)
            return

    await state.clear()
    await edit_message(callback, get_message(
        "meeting_rescheduled", lang, date=new.date_str, time=new.time_str,
        address=OFFICE_CONTACTS[f"address_{lang}"], late=LATE_WARNING[lang],
    ))
    await callback.answer()
    await callback.message.answer_location(latitude=OFFICE_CONTACTS["latitude"], longitude=OFFICE_CONTACTS["longitude"])
    spawn(notify_staff(
        bot,
        staff_booking_text("🔄 Встреча перенесена клиентом", new, footer=f"Было: {old.date_str} {old.time_str}"),
        tg_profile_kb(new.creator_tg_id, new.creator_username),
    ))
