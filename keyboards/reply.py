from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from locales.messages import get_message

CLIENT_BUTTONS = {
    "book": {"ru": "📝 Записаться на встречу", "uz": "📝 Uchrashuvga yozilish"},
    "cancel": {"ru": "❌ Отменить встречу", "uz": "❌ Uchrashuvni bekor qilish"},
    "my": {"ru": "📋 Мои встречи", "uz": "📋 Mening uchrashuvlarim"},
    "reschedule": {"ru": "📅 Перенести встречу", "uz": "📅 Uchrashuvni ko'chirish"},
    "contacts": {"ru": "📞 Контакты", "uz": "📞 Kontaktlar"},
    "language": {"ru": "🌐 O'zbek tili", "uz": "🌐 Русский язык"},
}

ADMIN_BUTTONS = {
    "staff": "👥 Персонал",
    "schedule": "🗓 Расписание CEO",
    "meetings": "📋 Список встреч",
    "report": "📊 Выгрузить отчёт",
    "contracts": "📄 Договоры",
    "holidays": "🎉 Праздничные дни",
    "settings": "⚙️ Настройки",
    "lookup": "🔍 Информация по договору",
}

BACK = "🔙 Назад"
CANCEL = "❌ Отменить"


def client_button_variants(key: str) -> list[str]:
    """Текст кнопки на всех языках — для фильтров F.text.in_()."""
    return list(CLIENT_BUTTONS[key].values())


def client_keyboard(lang: str = "ru") -> ReplyKeyboardMarkup:
    b = {key: KeyboardButton(text=texts[lang]) for key, texts in CLIENT_BUTTONS.items()}
    return ReplyKeyboardMarkup(
        keyboard=[
            [b["language"]],
            [b["book"], b["cancel"]],
            [b["my"], b["reschedule"]],
            [b["contacts"]],
        ],
        resize_keyboard=True,
    )


def admin_keyboard() -> ReplyKeyboardMarkup:
    t = ADMIN_BUTTONS
    rows = [
        [t["meetings"], t["report"]],
        [t["schedule"], t["holidays"]],
        [t["contracts"], t["lookup"]],
        [t["staff"], t["settings"]],
    ]
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],
        resize_keyboard=True,
    )


def employee_keyboard() -> ReplyKeyboardMarkup:
    t = ADMIN_BUTTONS
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t["meetings"]), KeyboardButton(text=t["report"])]],
        resize_keyboard=True,
    )


def phone_request_keyboard(lang: str = "ru") -> ReplyKeyboardMarkup:
    text = get_message("btn_send_phone", lang)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=CLIENT_BUTTONS["language"][lang])],
            [KeyboardButton(text=text, request_contact=True)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
