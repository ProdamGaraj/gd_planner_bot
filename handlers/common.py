from aiogram import F, Router, types
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext

from config import OFFICE_CONTACTS
from database.session import SessionLocal
from keyboards.reply import (
    admin_keyboard, client_button_variants, client_keyboard, employee_keyboard,
)
from locales.messages import get_message
from services.auth import ROLE_ADMIN, ROLE_EMPLOYEE, get_role
from services.users import get_user_language, toggle_language

router = Router()


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    role = get_role(user.id)

    if role == ROLE_ADMIN:
        await message.answer(get_message("welcome_admin"), parse_mode="HTML", reply_markup=admin_keyboard())
        return
    if role == ROLE_EMPLOYEE:
        await message.answer(get_message("welcome_employee"), parse_mode="HTML", reply_markup=employee_keyboard())
        return

    with SessionLocal() as session:
        lang = get_user_language(session, user.id, user.language_code)
    await message.answer(get_message("welcome", lang), reply_markup=client_keyboard(lang))


# Во время записи язык переключает handlers/booking.py (с повтором текущего шага)
@router.message(F.text.in_(client_button_variants("language")), StateFilter(None))
async def language_toggle(message: types.Message, state: FSMContext):
    await state.clear()
    with SessionLocal() as session:
        lang = toggle_language(session, message.from_user.id)
    await message.answer(get_message("language_changed", lang), reply_markup=client_keyboard(lang))


@router.message(F.text.in_(client_button_variants("contacts")))
async def contacts(message: types.Message, state: FSMContext):
    await state.clear()
    with SessionLocal() as session:
        lang = get_user_language(session, message.from_user.id)
    c = OFFICE_CONTACTS
    await message.answer(
        get_message(
            "contacts", lang,
            phone=c["phone"],
            address=c[f"address_{lang}"],
            hours=c[f"working_hours_{lang}"],
        ),
        parse_mode="HTML",
        reply_markup=client_keyboard(lang),
    )
    await message.answer_location(latitude=c["latitude"], longitude=c["longitude"])
