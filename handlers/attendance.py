"""Кнопки «Пришёл» / «Не пришёл» в запросе явки. Нажимать может любой админ."""
from aiogram import Bot, F, Router, types

from database.session import SessionLocal
from handlers.utils import edit_message
from services.attendance import (
    LABELS, AttCb, AttendanceError, fix_kb, mark_attendance, prompt_kb, refresh_prompts, result_text,
)
from services.auth import IsAdminFilter
from services.booking import booking_info
from services.notify import spawn

router = Router()
router.callback_query.filter(IsAdminFilter())


@router.callback_query(AttCb.filter(F.action == "fix"))
async def attendance_fix(callback: types.CallbackQuery, callback_data: AttCb):
    """Показать кнопки заново — следующая отметка перезапишет текущую."""
    await callback.answer("Выберите правильную отметку")
    await callback.message.edit_reply_markup(reply_markup=prompt_kb(callback_data.booking_id, force=True))


@router.callback_query(AttCb.filter(F.action.in_({"came", "no_show"})))
async def attendance_mark(callback: types.CallbackQuery, callback_data: AttCb, bot: Bot):
    admin = callback.from_user
    with SessionLocal() as session:
        try:
            b = mark_attendance(session, callback_data.booking_id, callback_data.action, admin.id,
                                admin.full_name, force=callback_data.force)
        except AttendanceError as e:
            if e.code == AttendanceError.ALREADY:
                # Другой админ успел раньше — показываем его отметку
                b = e.booking
                await edit_message(callback, result_text(booking_info(b), b), fix_kb(b.id), parse_mode="HTML")
                await callback.answer(f"Уже отмечено: {LABELS[b.attendance]} ({b.attendance_by_name})", show_alert=True)
            elif e.code == AttendanceError.CANCELLED:
                await callback.answer("Встреча отменена — явку не отмечаем", show_alert=True)
            elif e.code == AttendanceError.NOT_STARTED:
                await callback.answer("Встреча ещё не началась", show_alert=True)
            else:
                await callback.answer("Встреча не найдена", show_alert=True)
            return
        text = result_text(booking_info(b), b)

    await edit_message(callback, text, fix_kb(callback_data.booking_id), parse_mode="HTML")
    await callback.answer(f"Отмечено: {LABELS[callback_data.action]}")
    spawn(refresh_prompts(bot, callback_data.booking_id, skip=(callback.message.chat.id, callback.message.message_id)))
