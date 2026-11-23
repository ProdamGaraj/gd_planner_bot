"""Уведомления персоналу и клиентам."""
import asyncio
import logging
from collections.abc import Coroutine
from html import escape

from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.session import SessionLocal
from locales.messages import get_message
from services.auth import staff_recipients
from services.booking import CANCELLED_BY_HOLIDAY, BookingInfo
from services.users import format_tg_contact_html, get_user_language

log = logging.getLogger(__name__)

# Ссылки на фоновые задачи, чтобы их не собрал GC до завершения
_background: set[asyncio.Task] = set()


def spawn(coro: Coroutine) -> asyncio.Task:
    """Запустить уведомление в фоне, не задерживая ответ клиенту."""
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs) -> bool:
    """Отправить сообщение. True — доставлено.

    TelegramRetryAfter (лимит частоты) — ждём и повторяем; пользователь
    заблокировал бота — False без исключения. Прочие ошибки пробрасываются.
    """
    for attempt in range(3):
        try:
            await bot.send_message(chat_id, text, **kwargs)
            return True
        except TelegramRetryAfter as e:
            log.warning("Лимит Telegram, ждём %s с (chat %s)", e.retry_after, chat_id)
            await asyncio.sleep(e.retry_after + 0.5)
        except TelegramForbiddenError:
            log.info("Пользователь %s заблокировал бота", chat_id)
            return False
    return False


def tg_profile_kb(telegram_id: int | None, username: str | None) -> types.InlineKeyboardMarkup | None:
    if username:
        url, text = f"https://t.me/{username}", f"👤 Открыть @{username}"
    elif telegram_id:
        url, text = f"tg://user?id={telegram_id}", "👤 Открыть профиль клиента"
    else:
        return None
    builder = InlineKeyboardBuilder()
    builder.button(text=text, url=url)
    return builder.as_markup()


def staff_booking_text(title: str, info: BookingInfo, footer: str | None = None) -> str:
    def v(value) -> str:
        return escape(str(value)) if value not in (None, "") else "—"

    lines = [
        f"<b>{escape(title)}</b>",
        "",
        f"👤 Клиент: {v(info.client_fio)}",
        f"📞 Тел: {v(info.phone)}",
        f"💬 TG: {format_tg_contact_html(info.creator_tg_id, info.creator_username)}",
        f"🏠 Объект: {v(info.house_name)}",
        f"🏢 Кв. {v(info.apt_num)}, подъезд {v(info.entrance)}, этаж {v(info.floor)}",
        f"📄 Договор: {v(info.contract_num)}",
        f"📅 Дата: {info.date_str}",
        f"⏰ Время: {info.time_str}",
        f"📝 Тема: {v(info.topic)}",
    ]
    if footer:
        lines += ["", escape(footer)]
    return "\n".join(lines)


async def send_staff_message(bot: Bot, chat_id: int, text: str, kb=None) -> None:
    """Если кнопка tg://user запрещена приватностью клиента — шлём без неё."""
    try:
        await safe_send(bot, chat_id, text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest as e:
        if kb is not None and "BUTTON_USER_PRIVACY_RESTRICTED" in str(e):
            await safe_send(bot, chat_id, text, parse_mode="HTML")
        else:
            raise


async def notify_staff(bot: Bot, text: str, kb=None) -> None:
    for chat_id in staff_recipients():
        try:
            await send_staff_message(bot, chat_id, text, kb)
        except Exception:
            log.exception("Не удалось уведомить сотрудника %s", chat_id)


async def notify_clients_company_cancel(bot: Bot, infos: list[BookingInfo], reason: str) -> int:
    """Сообщить клиентам об отмене встречи со стороны компании. Возвращает число доставленных."""
    reason_key = "cancel_reason_holiday" if reason == CANCELLED_BY_HOLIDAY else "cancel_reason_ceo"
    sent = 0
    for info in infos:
        if not info.owner_tg_id:
            continue
        with SessionLocal() as session:
            lang = get_user_language(session, info.owner_tg_id)
        text = get_message(
            "meeting_cancelled_by_company", lang,
            date=info.date_str, time=info.time_str,
            reason=get_message(reason_key, lang),
        )
        try:
            if await safe_send(bot, info.owner_tg_id, text):
                sent += 1
            await asyncio.sleep(0.05)  # не упираться в лимит Telegram при массовой отмене
        except Exception:
            log.exception("Не удалось уведомить клиента %s об отмене #%s", info.owner_tg_id, info.id)
    return sent
