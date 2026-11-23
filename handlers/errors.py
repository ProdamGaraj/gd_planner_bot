"""Глобальный обработчик ошибок: пишем в лог и не оставляем пользователя без ответа."""
import logging

from aiogram import Router
from aiogram.types import ErrorEvent

log = logging.getLogger(__name__)

router = Router()

ERROR_TEXT = (
    "⚠️ Что-то пошло не так. Попробуйте ещё раз или начните заново через /start.\n"
    "⚠️ Xatolik yuz berdi. Qayta urinib ko'ring yoki /start orqali qaytadan boshlang."
)


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    log.error("Ошибка при обработке апдейта %s", event.update.update_id, exc_info=event.exception)
    try:
        if event.update.callback_query:
            await event.update.callback_query.answer(ERROR_TEXT[:200], show_alert=True)
        elif event.update.message:
            await event.update.message.answer(ERROR_TEXT)
    except Exception:
        log.exception("Не удалось сообщить пользователю об ошибке")
    return True
