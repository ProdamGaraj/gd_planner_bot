"""Язык и сохранённый телефон пользователя; ссылки на Telegram-профиль."""
from html import escape

from sqlalchemy.orm import Session

from database.models import UserSettings

LANGUAGES = ("ru", "uz")


def _get_or_create(session: Session, telegram_id: int, language_code: str | None = None) -> UserSettings:
    user = session.get(UserSettings, telegram_id)
    if user is None:
        lang = "uz" if language_code and language_code.startswith("uz") else "ru"
        user = UserSettings(telegram_id=telegram_id, language=lang)
        session.add(user)
        session.commit()
    return user


def get_user_language(session: Session, telegram_id: int, language_code: str | None = None) -> str:
    return _get_or_create(session, telegram_id, language_code).language


def set_user_language(session: Session, telegram_id: int, language: str) -> None:
    if language not in LANGUAGES:
        raise ValueError(f"Неизвестный язык: {language}")
    user = _get_or_create(session, telegram_id)
    user.language = language
    session.commit()


def toggle_language(session: Session, telegram_id: int) -> str:
    new_lang = "uz" if get_user_language(session, telegram_id) == "ru" else "ru"
    set_user_language(session, telegram_id, new_lang)
    return new_lang


def get_user_phone(session: Session, telegram_id: int) -> str | None:
    user = session.get(UserSettings, telegram_id)
    return user.phone if user else None


def set_user_phone(session: Session, telegram_id: int, phone: str) -> None:
    user = _get_or_create(session, telegram_id)
    user.phone = phone
    session.commit()


def build_tg_href(telegram_id: int | None, username: str | None) -> str | None:
    if username:
        return f"https://t.me/{username}"
    if telegram_id:
        return f"tg://user?id={telegram_id}"
    return None


def format_tg_contact_html(telegram_id: int | None, username: str | None) -> str:
    if username:
        safe = escape(username)
        return f'<a href="https://t.me/{safe}">@{safe}</a>'
    if telegram_id:
        return f'<a href="tg://user?id={telegram_id}">профиль</a>'
    return "—"
