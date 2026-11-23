"""Последний роутер: бот никогда не молчит."""
from aiogram import Router, types

from database.session import SessionLocal
from handlers.utils import user_lang
from keyboards.reply import admin_keyboard, client_keyboard, employee_keyboard
from locales.messages import get_message
from services.auth import ROLE_ADMIN, ROLE_EMPLOYEE, get_role

router = Router()


@router.callback_query()
async def stale_callback(callback: types.CallbackQuery):
    """Кнопка из старого сообщения (шаг уже пройден или бот перезапускался)."""
    with SessionLocal() as session:
        lang = user_lang(session, callback.from_user)
    await callback.answer(get_message("session_expired", lang), show_alert=True)


@router.message()
async def unknown_message(message: types.Message):
    role = get_role(message.from_user.id)
    if role == ROLE_ADMIN:
        await message.answer("Используйте кнопки меню 👇", reply_markup=admin_keyboard())
        return
    if role == ROLE_EMPLOYEE:
        await message.answer("Используйте кнопки меню 👇", reply_markup=employee_keyboard())
        return
    with SessionLocal() as session:
        lang = user_lang(session, message.from_user)
    await message.answer(get_message("use_menu", lang), reply_markup=client_keyboard(lang))
