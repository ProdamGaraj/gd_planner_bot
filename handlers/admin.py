"""Админ-панель: расписание CEO, праздники, договоры, поиск договора, персонал, настройки.

Кнопки меню зарегистрированы первыми — они прерывают любой ввод.
"""
import logging
from datetime import date, datetime, timedelta
from html import escape

from aiogram import Bot, F, Router, types
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_ID
from database.models import Booking, Contract
from database.session import SessionLocal
from handlers.staff import WEEKDAYS_RU
from handlers.states import AdminSteps
from handlers.utils import download_document, edit_message, send_long
from keyboards.reply import ADMIN_BUTTONS, admin_keyboard
from services import booking_time
from services.auth import ROLE_ADMIN, ROLE_EMPLOYEE, IsAdminFilter
from services.availability import horizon_date
from services.attendance import attendance_label, refresh_prompts
from services.booking_time import active_booking_filter, slot_start
from services.booking import (
    CANCELLED_BY_BLOCK, CANCELLED_BY_HOLIDAY, BookingInfo, booking_info, cancel_by_company, find_contract,
    no_show_ban,
)
from services.ceo_schedule import block_slot, close_day, day_overview, open_day, unblock_slot
from services.contracts import binding_log, contract_history, contract_stats, rebind_contract, unbind_contract
from services.excel import import_contracts
from services.holidays import export_holidays_excel, get_all_holidays, import_holidays_from_excel
from services.notify import notify_clients_company_cancel, notify_staff, spawn
from services.reports import CANCEL_REASONS, contracts_export
from services.schedule import is_working_day
from services.settings import (
    MAX_COOLDOWN_DAYS, MAX_NO_SHOW_BAN_DAYS, get_cooldown_days, get_no_show_ban_days, set_cooldown_days,
    set_no_show_ban_days,
)
from services.staff import add_staff, list_staff, remove_staff
from services.users import format_tg_contact_html

log = logging.getLogger(__name__)

router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())

DATE_FMT = "%d.%m.%Y"
EXCEL_EXT = (".xlsx", ".xls")


class SchCb(CallbackData, prefix="sch"):
    # day | block | blockq | blocky | unblock | close | closeq | closey | open | pick
    action: str
    value: str = ""  # YYYY-MM-DD или YYYY-MM-DD_HHMM


class AdmCb(CallbackData, prefix="adm"):
    # hol_dl | hol_cancel | hol_keep | ctr_dl | unbind | unbind_yes | rebind |
    # staff_admin | staff_employee | staff_rm | cooldown
    action: str
    value: str = ""


def _v(value) -> str:
    return escape(str(value)) if value not in (None, "") else "—"


def _btn(text: str, cb: CallbackData) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb.pack())


def _day_label(day: date) -> str:
    return f"{WEEKDAYS_RU[day.weekday()]}, {day.strftime(DATE_FMT)}"


def _parse_date(text: str) -> date | None:
    for fmt in (DATE_FMT, "%d.%m.%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _cancelled_summary(infos: list[BookingInfo], delivered: int) -> str:
    if not infos:
        return ""
    lines = "\n".join(f"  • {i.date_str} {i.time_str} — {_v(i.client_fio)} (дог. {_v(i.contract_num)})" for i in infos)
    return f"\n\nОтменено встреч: {len(infos)}, клиентов уведомлено: {delivered}\n{lines}"


# ===================== Кнопки меню =====================

@router.message(F.text == ADMIN_BUTTONS["schedule"])
async def schedule_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(AdminSteps.schedule_date)
    await message.answer(
        "🗓 <b>Расписание CEO</b>\n\nВыберите день или введите дату в формате ДД.ММ.ГГГГ.\n"
        "В дне можно закрыть отдельные слоты или весь день (встречи на закрытом времени отменяются "
        "с уведомлением клиентов).",
        parse_mode="HTML",
        reply_markup=_day_picker_kb(),
    )


@router.message(F.text == ADMIN_BUTTONS["holidays"])
async def holidays_menu(message: types.Message, state: FSMContext):
    await state.clear()
    today = booking_time.now_tashkent().date()
    with SessionLocal() as session:
        upcoming = [h for h in get_all_holidays(session) if h.date >= today]
    lines = "\n".join(f"  • {h.date.strftime(DATE_FMT)}" + (f" — {_v(h.description)}" if h.description else "")
                      for h in upcoming) or "  нет"
    await state.set_state(AdminSteps.holidays_file)
    await message.answer(
        f"🎉 <b>Праздничные дни</b> (предстоящие):\n{lines}\n\n"
        "Чтобы заменить список, отправьте Excel-файл со столбцами «Дата» (ДД.ММ.ГГГГ) и «Описание». "
        "Список заменяется целиком — скачайте текущий, поправьте и загрузите.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_btn("📥 Скачать текущий список", AdmCb(action="hol_dl"))]]),
    )


@router.message(F.text == ADMIN_BUTTONS["contracts"])
async def contracts_menu(message: types.Message, state: FSMContext):
    await state.clear()
    with SessionLocal() as session:
        total, bound = contract_stats(session)
    await state.set_state(AdminSteps.contracts_file)
    await message.answer(
        f"📄 <b>Договоры</b>\n\nВсего: {total}, привязано к Telegram: {bound}\n\n"
        "Чтобы добавить или обновить договоры, отправьте Excel-файл в формате dks_bot "
        "(Название дома, Номер квартиры, Подъезд, Этаж, Номер договора, ФИО клиента, Дата сдачи). "
        "Привязки к Telegram и встречи не меняются.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_btn("📥 Скачать текущие договоры", AdmCb(action="ctr_dl"))]]),
    )


@router.message(F.text == ADMIN_BUTTONS["lookup"])
async def lookup_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(AdminSteps.lookup_contract)
    await message.answer("🔍 Введите номер договора:")


@router.message(F.text == ADMIN_BUTTONS["staff"])
async def staff_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await _send_staff_list(message)


@router.message(F.text == ADMIN_BUTTONS["settings"])
async def settings_menu(message: types.Message, state: FSMContext):
    await state.clear()
    with SessionLocal() as session:
        cooldown = get_cooldown_days(session)
        ban_days = get_no_show_ban_days(session)
    await message.answer(
        f"⚙️ <b>Настройки</b>\n\n⏳ Кулдаун между встречами: <b>{cooldown}</b> дн.\n"
        "Клиент может записаться снова не раньше чем через столько дней после прошлой встречи "
        "по тому же договору. 0 — без ограничения.\n\n"
        f"⛔ Бан за неявку: <b>{ban_days}</b> дн.\n"
        "Если админ отметил «Не пришёл», следующая встреча по договору — не раньше даты пропущенной "
        "встречи + столько дней. 0 — без бана. Исправление отметки на «Пришёл» снимает бан.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("✏️ Изменить кулдаун", AdmCb(action="cooldown"))],
            [_btn("✏️ Изменить бан за неявку", AdmCb(action="noshow_ban"))],
        ]),
    )


# ===================== Расписание CEO =====================

def _day_picker_kb() -> InlineKeyboardMarkup:
    """Ближайшие 10 рабочих дней (без учёта праздников — их можно открыть и посмотреть)."""
    day = booking_time.now_tashkent().date()
    days = []
    while len(days) < 10:
        if is_working_day(day):
            days.append(day)
        day += timedelta(days=1)
    rows = [[_btn(_day_label(d), SchCb(action="day", value=d.isoformat())) for d in days[i:i + 2]]
            for i in range(0, len(days), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _day_view(session, day: date) -> tuple[str, InlineKeyboardMarkup]:
    ov = day_overview(session, day)
    iso = day.isoformat()
    lines = [f"🗓 <b>{_day_label(day)}</b>"]
    if not ov.working:
        lines.append("ℹ️ Выходной или праздник — клиенты на этот день не записываются.")
    if ov.closed:
        lines.append("⛔ <b>День закрыт целиком.</b>")
    lines.append("")
    rows = []
    for s in ov.slots:
        t, key = s.slot.strftime("%H:%M"), f"{iso}_{s.slot.strftime('%H%M')}"
        if s.booking:
            info = booking_info(s.booking)
            lines.append(f"{t} 👤 {_v(info.client_fio)}, кв. {_v(info.apt_num)}")
            if not ov.closed:
                rows.append(_btn(f"⛔ {t} 👤", SchCb(action="blockq", value=key)))
        elif s.blocked:
            lines.append(f"{t} ⛔ закрыто")
            rows.append(_btn(f"✅ {t}", SchCb(action="unblock", value=key)))
        else:
            lines.append(f"{t} ✅ свободно")
            if not ov.closed:
                rows.append(_btn(f"⛔ {t}", SchCb(action="block", value=key)))
    lines.append("\n⛔ — закрыть слот, ✅ — открыть.")

    kb_rows = [rows[i:i + 3] for i in range(0, len(rows), 3)]
    if ov.closed:
        kb_rows.append([_btn("✅ Открыть день", SchCb(action="open", value=iso))])
    else:
        kb_rows.append([_btn("⛔ Закрыть весь день", SchCb(action="closeq", value=iso))])
    kb_rows.append([_btn("📅 Другой день", SchCb(action="pick"))])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb_rows)


def _split_key(value: str):
    iso, hhmm = value.split("_")
    return date.fromisoformat(iso), datetime.strptime(hhmm, "%H%M").time()


@router.message(AdminSteps.schedule_date, F.text)
async def schedule_date_entered(message: types.Message):
    day = _parse_date(message.text)
    today = booking_time.now_tashkent().date()
    if day is None:
        await message.answer("❌ Не понял дату. Формат: ДД.ММ.ГГГГ, например 24.11.2026")
        return
    if day < today:
        await message.answer("❌ Дата в прошлом.")
        return
    with SessionLocal() as session:
        text, kb = _day_view(session, day)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


async def _show_day(callback: types.CallbackQuery, day: date) -> None:
    with SessionLocal() as session:
        text, kb = _day_view(session, day)
    await edit_message(callback, text, kb, parse_mode="HTML")


@router.callback_query(SchCb.filter(F.action == "pick"))
async def schedule_pick(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminSteps.schedule_date)
    await callback.answer()
    await edit_message(callback, "🗓 Выберите день или введите дату ДД.ММ.ГГГГ:", _day_picker_kb())


@router.callback_query(SchCb.filter(F.action == "day"))
async def schedule_day(callback: types.CallbackQuery, callback_data: SchCb):
    await callback.answer()
    await _show_day(callback, date.fromisoformat(callback_data.value))


@router.callback_query(SchCb.filter(F.action == "block"))
async def schedule_block(callback: types.CallbackQuery, callback_data: SchCb, bot: Bot):
    day, slot = _split_key(callback_data.value)
    with SessionLocal() as session:
        cancelled = block_slot(session, day, slot, callback.from_user.id)
    await _after_block(callback, bot, day, cancelled, f"слот {slot.strftime('%H:%M')}")


@router.callback_query(SchCb.filter(F.action == "blockq"))
async def schedule_block_ask(callback: types.CallbackQuery, callback_data: SchCb):
    day, slot = _split_key(callback_data.value)
    with SessionLocal() as session:
        bookings = [booking_info(b) for b in day_overview(session, day).bookings if b.time_slot == slot]
    if not bookings:  # клиент успел отменить — закрываем без вопросов
        await _show_day(callback, day)
        await callback.answer("Встреча уже отменена, нажмите ещё раз", show_alert=True)
        return
    i = bookings[0]
    await callback.answer()
    await edit_message(
        callback,
        f"⚠️ На {_day_label(day)} {i.time_str} записан клиент:\n{_v(i.client_fio)}, кв. {_v(i.apt_num)} "
        f"(дог. {_v(i.contract_num)}), тел. {_v(i.phone)}\n\n"
        "Закрыть слот и отменить встречу? Клиент получит уведомление.",
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("⛔ Закрыть и отменить встречу", SchCb(action="blocky", value=callback_data.value))],
            [_btn("↩️ Назад", SchCb(action="day", value=day.isoformat()))],
        ]),
        parse_mode="HTML",
    )


@router.callback_query(SchCb.filter(F.action == "blocky"))
async def schedule_block_confirmed(callback: types.CallbackQuery, callback_data: SchCb, bot: Bot):
    await schedule_block(callback, callback_data, bot)


@router.callback_query(SchCb.filter(F.action == "unblock"))
async def schedule_unblock(callback: types.CallbackQuery, callback_data: SchCb):
    day, slot = _split_key(callback_data.value)
    with SessionLocal() as session:
        unblock_slot(session, day, slot)
    await callback.answer(f"Слот {slot.strftime('%H:%M')} открыт")
    await _show_day(callback, day)


@router.callback_query(SchCb.filter(F.action == "closeq"))
async def schedule_close_ask(callback: types.CallbackQuery, callback_data: SchCb, bot: Bot):
    day = date.fromisoformat(callback_data.value)
    with SessionLocal() as session:
        bookings = [booking_info(b) for b in day_overview(session, day).bookings]
    if not bookings:
        await schedule_close(callback, callback_data, bot)
        return
    lines = "\n".join(f"  • {i.time_str} — {_v(i.client_fio)}, кв. {_v(i.apt_num)}" for i in bookings)
    await callback.answer()
    await edit_message(
        callback,
        f"⚠️ На {_day_label(day)} записано клиентов: {len(bookings)}\n{lines}\n\n"
        "Закрыть день и отменить все встречи? Клиенты получат уведомления.",
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("⛔ Закрыть день и отменить встречи", SchCb(action="closey", value=callback_data.value))],
            [_btn("↩️ Назад", SchCb(action="day", value=callback_data.value))],
        ]),
        parse_mode="HTML",
    )


@router.callback_query(SchCb.filter(F.action.in_({"close", "closey"})))
async def schedule_close(callback: types.CallbackQuery, callback_data: SchCb, bot: Bot):
    day = date.fromisoformat(callback_data.value)
    with SessionLocal() as session:
        cancelled = close_day(session, day, callback.from_user.id)
    await _after_block(callback, bot, day, cancelled, "весь день")


@router.callback_query(SchCb.filter(F.action == "open"))
async def schedule_open(callback: types.CallbackQuery, callback_data: SchCb):
    day = date.fromisoformat(callback_data.value)
    with SessionLocal() as session:
        open_day(session, day)
    await callback.answer("День открыт")
    await _show_day(callback, day)


async def _after_block(callback, bot: Bot, day: date, cancelled: list[BookingInfo], what: str) -> None:
    delivered = await notify_clients_company_cancel(bot, cancelled, CANCELLED_BY_BLOCK) if cancelled else 0
    await callback.answer(f"Закрыт {what}" + (f", отменено встреч: {len(cancelled)}" if cancelled else ""))
    await _show_day(callback, day)
    for info in cancelled:  # встреча могла уже начаться — убрать кнопки явки у админов
        spawn(refresh_prompts(bot, info.id))
    if cancelled:
        admin = callback.from_user
        spawn(notify_staff(bot, (
            f"⛔ <b>Время CEO закрыто</b>: {_day_label(day)}, {escape(what)}\n"
            f"Закрыл: {escape(admin.full_name)}" + _cancelled_summary(cancelled, delivered)
        )))


# ===================== Праздники =====================

@router.callback_query(AdmCb.filter(F.action == "hol_dl"))
async def holidays_download(callback: types.CallbackQuery):
    with SessionLocal() as session:
        data = export_holidays_excel(session)
    await callback.answer()
    await callback.message.answer_document(BufferedInputFile(data, filename="holidays.xlsx"))


@router.message(AdminSteps.holidays_file, F.document)
async def holidays_upload(message: types.Message, state: FSMContext, bot: Bot):
    if not (message.document.file_name or "").lower().endswith(EXCEL_EXT):
        await message.answer("⚠️ Нужен Excel-файл (.xlsx)")
        return
    buf = await download_document(bot, message.document)
    today = booking_time.now_tashkent().date()
    with SessionLocal() as session:
        try:
            count = import_holidays_from_excel(session, buf)
        except Exception as e:  # битый файл или неверная дата — список не трогаем
            session.rollback()
            log.warning("Ошибка импорта праздников: %r", e)
            await message.answer(f"❌ {e}\nСписок не изменён.")
            return
        holiday_dates = [h.date for h in get_all_holidays(session) if h.date >= today]
        conflicts = (
            session.query(Booking)
            .filter(Booking.is_cancelled.is_(False), Booking.date.in_(holiday_dates), active_booking_filter())
            .order_by(Booking.date, Booking.time_slot)
            .all()
        ) if holiday_dates else []
        infos = [booking_info(b) for b in conflicts]

    await state.clear()
    await message.answer(f"✅ Список праздников обновлён: {count} дн.", reply_markup=admin_keyboard())
    if infos:
        await state.set_state(AdminSteps.holidays_conflicts)
        await state.update_data(conflict_ids=[i.id for i in infos])
        lines = "\n".join(f"  • {i.date_str} {i.time_str} — {_v(i.client_fio)} (дог. {_v(i.contract_num)})"
                          for i in infos)
        await send_long(
            message,
            f"⚠️ На праздничные дни есть встречи ({len(infos)}):\n{lines}\n\nЧто сделать?",
            InlineKeyboardMarkup(inline_keyboard=[
                [_btn("✅ Отменить и уведомить клиентов", AdmCb(action="hol_cancel"))],
                [_btn("⏭ Оставить как есть", AdmCb(action="hol_keep"))],
            ]),
        )


@router.callback_query(AdminSteps.holidays_conflicts, AdmCb.filter(F.action == "hol_cancel"))
async def holidays_conflicts_cancel(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    ids = (await state.get_data()).get("conflict_ids", [])
    await state.clear()
    with SessionLocal() as session:
        cancelled = cancel_by_company(session, ids, CANCELLED_BY_HOLIDAY)
    delivered = await notify_clients_company_cancel(bot, cancelled, CANCELLED_BY_HOLIDAY)
    for info in cancelled:
        spawn(refresh_prompts(bot, info.id))
    await callback.answer()
    await edit_message(callback, f"✅ Отменено встреч: {len(cancelled)}, клиентов уведомлено: {delivered}.")


@router.callback_query(AdminSteps.holidays_conflicts, AdmCb.filter(F.action == "hol_keep"))
async def holidays_conflicts_keep(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await edit_message(callback, "⏭ Встречи оставлены. Клиенты смогут отменить их до начала встречи.")


# ===================== Договоры =====================

@router.callback_query(AdmCb.filter(F.action == "ctr_dl"))
async def contracts_download(callback: types.CallbackQuery):
    with SessionLocal() as session:
        data = contracts_export(session)
    await callback.answer()
    await callback.message.answer_document(BufferedInputFile(data, filename="contracts.xlsx"))


@router.message(AdminSteps.contracts_file, F.document)
async def contracts_upload(message: types.Message, state: FSMContext, bot: Bot):
    if not (message.document.file_name or "").lower().endswith(EXCEL_EXT):
        await message.answer("⚠️ Нужен Excel-файл (.xlsx)")
        return
    buf = await download_document(bot, message.document)
    with SessionLocal() as session:
        try:
            r = import_contracts(session, buf)
        except Exception as e:  # битый/не тот файл: ничего не сохранено (сессия откатится)
            session.rollback()
            log.warning("Ошибка импорта договоров: %r", e)
            await message.answer(f"❌ Не удалось прочитать файл: {e}\nНичего не изменено.")
            return
    await state.clear()
    text = (f"✅ Договоры загружены.\n\nДобавлено: {r.added}\nОбновлено: {r.updated}\n"
            f"Без номера договора: {r.empty}")
    if r.duplicates:
        shown = ", ".join(r.duplicates[:30]) + (f" и ещё {len(r.duplicates) - 30}" if len(r.duplicates) > 30 else "")
        text += (f"\n\n⚠️ Номера договоров, повторяющиеся в файле ({len(r.duplicates)}): {shown}\n"
                 "Сохранена последняя строка с каждым номером — проверьте эти договоры.")
    if r.warnings:
        shown = "\n".join(r.warnings[:15]) + (f"\n… и ещё {len(r.warnings) - 15}" if len(r.warnings) > 15 else "")
        text += f"\n\n⚠️ Пропущенные значения ({len(r.warnings)}):\n{shown}"
    await message.answer(text, reply_markup=admin_keyboard())


@router.message(AdminSteps.holidays_file)
@router.message(AdminSteps.contracts_file)
async def waiting_file(message: types.Message):
    await message.answer("📎 Отправьте Excel-файл (.xlsx) или выберите раздел в меню.")


# ===================== Информация по договору =====================

def _contract_card(session, contract: Contract) -> tuple[str, InlineKeyboardMarkup]:
    lines = [
        f"📄 <b>Договор {_v(contract.contract_num)}</b>",
        f"👤 {_v(contract.client_fio)}",
        f"🏠 {_v(contract.house_name)}, кв. {_v(contract.apt_num)}, подъезд {_v(contract.entrance)}, "
        f"этаж {_v(contract.floor)}",
        f"🔑 Дата сдачи: {contract.delivery_date.strftime(DATE_FMT) if contract.delivery_date else '—'}",
        f"💬 Telegram: {format_tg_contact_html(contract.telegram_id, contract.username)}"
        + (f" (ID {contract.telegram_id})" if contract.telegram_id else " — не привязан"),
    ]
    ban = no_show_ban(session, contract.id)
    if ban:
        lines.append(f"⛔ Неявка {ban[0].strftime(DATE_FMT)} — запись не раньше {ban[1].strftime(DATE_FMT)}")
    lines += [
        "",
        "<b>Встречи</b> (последние 10):",
    ]
    history = contract_history(session, contract.id)
    if not history:
        lines.append("  нет")
    now = booking_time.now_tashkent()
    for b in history:
        if b.is_cancelled:
            status = CANCEL_REASONS.get(b.cancelled_by, "отменена")
        elif slot_start(b.date, b.time_slot) <= now:
            status = f"явка: {attendance_label(b)}"
        else:
            status = "активна"
        lines.append(f"  • {b.date.strftime(DATE_FMT)} {b.time_slot.strftime('%H:%M')} — {escape(status)}")
    logs = binding_log(session, contract.id)
    if logs:
        lines += ["", "<b>Изменения привязки:</b>"]
        for entry in logs:
            lines.append(f"  • {entry.created_at.strftime('%d.%m.%Y %H:%M')} {entry.action}: "
                         f"{entry.old_telegram_id or '—'} → {entry.new_telegram_id or '—'} (админ {entry.admin_telegram_id})")

    rows = []
    if contract.telegram_id:
        rows.append([_btn("🔓 Отвязать Telegram", AdmCb(action="unbind", value=str(contract.id)))])
    rows.append([_btn("🔗 Привязать к Telegram ID", AdmCb(action="rebind", value=str(contract.id)))])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(AdminSteps.lookup_contract, F.text)
async def lookup_entered(message: types.Message, state: FSMContext):
    with SessionLocal() as session:
        contract = find_contract(session, message.text)
        if contract is None:
            await message.answer("❌ Договор не найден. Введите другой номер или выберите раздел в меню.")
            return
        text, kb = _contract_card(session, contract)
    await state.clear()
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(AdmCb.filter(F.action == "unbind"))
async def unbind_ask(callback: types.CallbackQuery, callback_data: AdmCb):
    await callback.answer()
    await callback.message.answer(
        "⚠️ Отвязать договор от Telegram-аккаунта?\nКлиент больше не сможет управлять встречами по договору; "
        "следующий, кто запишется по этому номеру, станет владельцем. Встречи не отменяются.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🔓 Да, отвязать", AdmCb(action="unbind_yes", value=callback_data.value))],
        ]),
    )


@router.callback_query(AdmCb.filter(F.action == "unbind_yes"))
async def unbind_confirmed(callback: types.CallbackQuery, callback_data: AdmCb):
    with SessionLocal() as session:
        contract = session.get(Contract, int(callback_data.value))
        if contract is None:
            await callback.answer("Договор не найден", show_alert=True)
            return
        if contract.telegram_id:
            unbind_contract(session, contract, callback.from_user.id, callback.from_user.username)
        text, kb = _contract_card(session, contract)
    await callback.answer("Отвязано")
    await edit_message(callback, text, kb, parse_mode="HTML")


@router.callback_query(AdmCb.filter(F.action == "rebind"))
async def rebind_ask(callback: types.CallbackQuery, callback_data: AdmCb, state: FSMContext):
    await state.set_state(AdminSteps.rebind_target)
    await state.update_data(contract_id=int(callback_data.value))
    await callback.answer()
    await callback.message.answer(
        "🔗 Введите числовой Telegram ID нового владельца.\n"
        "Клиент может узнать свой ID, например, через @userinfobot."
    )


@router.message(AdminSteps.rebind_target, F.text)
async def rebind_entered(message: types.Message, state: FSMContext):
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer("❌ Нужен числовой ID, например 123456789.")
        return
    contract_id = (await state.get_data())["contract_id"]
    with SessionLocal() as session:
        contract = session.get(Contract, contract_id)
        rebind_contract(session, contract, int(raw), message.from_user.id, message.from_user.username)
        text, kb = _contract_card(session, contract)
    await state.clear()
    await message.answer("✅ Договор перепривязан.", reply_markup=admin_keyboard())
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


# ===================== Персонал =====================

async def _send_staff_list(message: types.Message) -> None:
    with SessionLocal() as session:
        staff = list_staff(session)
    roles = {ROLE_ADMIN: "админ", ROLE_EMPLOYEE: "сотрудник"}
    lines = [f"👥 <b>Персонал</b>\n\n👑 {ADMIN_ID} — супер-админ (из .env)"]
    lines += [f"• {s.telegram_id} — {roles.get(s.role, s.role)}" for s in staff]
    lines.append("\nАдмины управляют всем, сотрудники видят список встреч и отчёт. "
                 "Все получают уведомления о записях.")
    rows = [[_btn("➕ Админ", AdmCb(action="staff_admin")), _btn("➕ Сотрудник", AdmCb(action="staff_employee"))]]
    rows += [[_btn(f"➖ Удалить {s.telegram_id} ({roles.get(s.role, s.role)})",
                   AdmCb(action="staff_rm", value=str(s.telegram_id)))] for s in staff]
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(AdmCb.filter(F.action.in_({"staff_admin", "staff_employee"})))
async def staff_add_ask(callback: types.CallbackQuery, callback_data: AdmCb, state: FSMContext):
    role = ROLE_ADMIN if callback_data.action == "staff_admin" else ROLE_EMPLOYEE
    await state.set_state(AdminSteps.staff_add_id)
    await state.update_data(role=role)
    await callback.answer()
    await callback.message.answer("Введите числовой Telegram ID сотрудника (узнать можно через @userinfobot):")


@router.message(AdminSteps.staff_add_id, F.text)
async def staff_add_entered(message: types.Message, state: FSMContext):
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer("❌ Нужен числовой ID, например 123456789.")
        return
    role = (await state.get_data())["role"]
    with SessionLocal() as session:
        ok = add_staff(session, int(raw), role)
    await state.clear()
    await message.answer("✅ Готово." if ok else "ℹ️ Это супер-админ из .env — его роль не меняется.",
                         reply_markup=admin_keyboard())
    await _send_staff_list(message)


@router.callback_query(AdmCb.filter(F.action == "staff_rm"))
async def staff_remove(callback: types.CallbackQuery, callback_data: AdmCb):
    with SessionLocal() as session:
        removed = remove_staff(session, int(callback_data.value))
    await callback.answer("Удалён" if removed else "Уже удалён")
    await _send_staff_list(callback.message)


# ===================== Настройки =====================

@router.callback_query(AdmCb.filter(F.action == "cooldown"))
async def cooldown_ask(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminSteps.cooldown_value)
    await callback.answer()
    await callback.message.answer(f"Введите кулдаун в днях (0–{MAX_COOLDOWN_DAYS}):")


@router.message(AdminSteps.cooldown_value, F.text)
async def cooldown_entered(message: types.Message, state: FSMContext):
    raw = message.text.strip()
    try:
        days = int(raw)
        with SessionLocal() as session:
            set_cooldown_days(session, days)
    except ValueError:
        await message.answer(f"❌ Нужно целое число от 0 до {MAX_COOLDOWN_DAYS}.")
        return
    await state.clear()
    note = ""
    if days > (horizon_date() - booking_time.now_tashkent().date()).days:
        note = "\n⚠️ Кулдаун больше окна записи — после встречи клиент какое-то время не увидит свободных дат."
    await message.answer(f"✅ Кулдаун: {days} дн.{note}", reply_markup=admin_keyboard())


@router.callback_query(AdmCb.filter(F.action == "noshow_ban"))
async def no_show_ban_ask(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminSteps.no_show_ban_value)
    await callback.answer()
    await callback.message.answer(f"Введите бан за неявку в днях (0–{MAX_NO_SHOW_BAN_DAYS}):")


@router.message(AdminSteps.no_show_ban_value, F.text)
async def no_show_ban_entered(message: types.Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        with SessionLocal() as session:
            set_no_show_ban_days(session, days)
    except ValueError:
        await message.answer(f"❌ Нужно целое число от 0 до {MAX_NO_SHOW_BAN_DAYS}.")
        return
    await state.clear()
    await message.answer(f"✅ Бан за неявку: {days} дн." + (" (выключен)" if days == 0 else ""),
                         reply_markup=admin_keyboard())
