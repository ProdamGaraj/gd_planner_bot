"""Прогон апдейтов через настоящий Dispatcher с перехватом запросов к Telegram API."""
import asyncio
import random
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendDocument, SendLocation, SendMessage
from aiogram.types import CallbackQuery, Chat, Contact, Document, Message, Update, User

from handlers import admin, attendance, booking, client, common, errors, fallback, staff

ROUTERS = [errors.router, attendance.router, staff.router, admin.router, common.router, client.router, booking.router, fallback.router]


class CaptureSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.requests = []

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        return True

    async def stream_content(self, *args, **kwargs):
        yield b""

    async def close(self):
        pass


class SlowCaptureSession(CaptureSession):
    """«Сеть» с задержкой: обработчики уступают управление, апдейты реально перемешиваются."""

    async def make_request(self, bot, method, timeout=None):
        await asyncio.sleep(random.uniform(0.005, 0.03))
        return await super().make_request(bot, method, timeout)


def make_dispatcher() -> Dispatcher:
    """Новый Dispatcher (и чистое FSM-хранилище) на каждый тест."""
    for r in ROUTERS:
        r._parent_router = None
    dp = Dispatcher()
    for r in ROUTERS:
        dp.include_router(r)
    return dp


class Client:
    """Клиент Telegram: шлёт апдейты и собирает ответы бота."""

    def __init__(self, dp: Dispatcher, user_id: int = 100, username: str | None = "client", slow: bool = False):
        self.dp = dp
        self.bot = Bot(token="42:TEST", session=SlowCaptureSession() if slow else CaptureSession())
        self.user = User(id=user_id, is_bot=False, first_name="T", username=username, language_code="ru")
        self.chat = Chat(id=user_id, type="private")
        self._update_id = 0

    @property
    def requests(self):
        return self.bot.session.requests

    async def _feed(self, **payload):
        self._update_id += 1
        self.requests.clear()
        await self.dp.feed_update(self.bot, Update(update_id=self._update_id, **payload))
        for _ in range(3):  # дать фоновым уведомлениям выполниться
            await asyncio.sleep(0)
        return list(self.requests)

    def _message(self, **kwargs) -> Message:
        return Message(message_id=self._update_id, date=datetime.now(), chat=self.chat, from_user=self.user, **kwargs)

    async def text(self, text: str):
        return await self._feed(message=self._message(text=text))

    async def contact(self, phone: str):
        contact = Contact(phone_number=phone, first_name="T", user_id=self.user.id)
        return await self._feed(message=self._message(contact=contact))

    async def press(self, data: str):
        bot_message = Message(message_id=999, date=datetime.now(), chat=self.chat,
                              from_user=User(id=42, is_bot=True, first_name="Bot"), text="...")
        cq = CallbackQuery(id=str(self._update_id), from_user=self.user, chat_instance="ci",
                           message=bot_message, data=data)
        return await self._feed(callback_query=cq)


def sent(requests, user_id: int | None = None) -> list[SendMessage]:
    return [r for r in requests if isinstance(r, SendMessage) and (user_id is None or r.chat_id == user_id)]


def texts(requests, user_id: int | None = None) -> list[str]:
    return [r.text for r in sent(requests, user_id)]


def edits(requests) -> list[EditMessageText]:
    return [r for r in requests if isinstance(r, EditMessageText)]


def alerts(requests) -> list[AnswerCallbackQuery]:
    return [r for r in requests if isinstance(r, AnswerCallbackQuery) and r.show_alert]


def locations(requests) -> list[SendLocation]:
    return [r for r in requests if isinstance(r, SendLocation)]


def buttons(markup) -> list[tuple[str, str]]:
    return [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]


def documents(requests) -> list[SendDocument]:
    return [r for r in requests if isinstance(r, SendDocument)]


async def send_document(client: "Client", file_name: str = "file.xlsx"):
    doc = Document(file_id="f1", file_unique_id="u1", file_name=file_name)
    return await client._feed(message=client._message(document=doc))
