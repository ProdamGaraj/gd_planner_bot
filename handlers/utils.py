from io import BytesIO

from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.orm import Session

from services.users import get_user_language


def user_lang(session: Session, user: types.User) -> str:
    return get_user_language(session, user.id, user.language_code)


MAX_MESSAGE = 4000


def split_text(text: str, limit: int = MAX_MESSAGE) -> list[str]:
    """Режет по абзацам, чтобы не превысить лимит Telegram (4096)."""
    chunks, current = [], ""
    for block in text.split("\n\n"):
        while len(block) > limit:  # одиночный гигантский абзац
            chunks.append(block[:limit])
            block = block[limit:]
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > limit:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


async def send_long(message: types.Message, text: str, kb=None, parse_mode: str = "HTML") -> None:
    """Отправить длинный текст несколькими сообщениями; кнопки — к последнему."""
    chunks = split_text(text)
    for i, chunk in enumerate(chunks):
        last = i == len(chunks) - 1
        await message.answer(chunk, parse_mode=parse_mode, reply_markup=kb if last else None)


async def download_document(bot: Bot, document: types.Document) -> BytesIO:
    buf = BytesIO()
    await bot.download(document, destination=buf)
    buf.seek(0)
    return buf


async def edit_message(callback: types.CallbackQuery, text: str, kb=None, parse_mode: str | None = None) -> None:
    """Редактировать сообщение с inline-кнопками; повторное нажатие не роняет хендлер."""
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
