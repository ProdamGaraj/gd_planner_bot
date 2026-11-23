"""Регрессии, найденные при подготовке к проду."""
import asyncio
import os
import subprocess
import sys
from datetime import date, datetime, time
from io import BytesIO
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import SendMessage

from database.models import Booking, Contract, Holiday, UserSettings
from handlers import admin as admin_handlers
from keyboards.reply import ADMIN_BUTTONS, CLIENT_BUTTONS
from services import booking_time
from services.ceo_schedule import block_slot, close_day
from services.excel import import_contracts
from services.notify import safe_send
from services.reminders import due_reminders, send_reminders
from tests.conftest import tashkent
from tests.harness import Client, alerts, make_dispatcher, send_document, sent, texts

CLIENT, OTHER, ADMIN = 100, 200, 1
MON, TUE = date(2026, 11, 23), date(2026, 11, 24)
NOW = tashkent(2026, 11, 23, 14, 0)  # Пн 14:00


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(booking_time, "now_tashkent", lambda: NOW)


def add_contract(session, num="1-GHP", owner=CLIENT):
    c = Contract(house_name="ОзМахал-D 8", contract_num=num, client_fio="Иванов", apt_num="1", telegram_id=owner)
    session.add(c)
    session.commit()
    return c


def add_booking(session, contract, d, t, created=datetime(2026, 11, 1)):
    b = Booking(contract_id=contract.id, user_telegram_id=contract.telegram_id, date=d, time_slot=t,
                client_phone="+998901234567", created_at=created)
    session.add(b)
    session.commit()
    return b


# ---------- закрытие сегодняшнего дня не трогает прошедшие встречи ----------

def test_close_today_keeps_past_meetings(db_session):
    past = add_booking(db_session, add_contract(db_session, "1-GHP"), MON, time(10, 0))     # уже была
    future = add_booking(db_session, add_contract(db_session, "2-GHP"), MON, time(16, 0))   # ещё будет
    cancelled = close_day(db_session, MON, ADMIN)
    assert [i.id for i in cancelled] == [future.id]
    db_session.refresh(past)
    assert not past.is_cancelled


def test_block_past_slot_cancels_nothing(db_session):
    past = add_booking(db_session, add_contract(db_session), MON, time(11, 0))
    assert block_slot(db_session, MON, time(11, 0), ADMIN) == []
    db_session.refresh(past)
    assert not past.is_cancelled


async def test_holiday_today_does_not_notify_past_meetings(db_session, monkeypatch):
    add_booking(db_session, add_contract(db_session, "1-GHP"), MON, time(10, 0))            # прошла
    add_booking(db_session, add_contract(db_session, "2-GHP", owner=OTHER), MON, time(17, 0))
    buf = BytesIO()
    pd.DataFrame({"Дата": ["23.11.2026"]}).to_excel(buf, index=False)
    buf.seek(0)
    monkeypatch.setattr(admin_handlers, "download_document", AsyncMock(return_value=buf))
    adm = Client(make_dispatcher(), user_id=ADMIN)
    await adm.text(ADMIN_BUTTONS["holidays"])
    reqs = await send_document(adm)
    assert "есть встречи (1)" in texts(reqs)[1] and "17:00" in texts(reqs)[1]


# ---------- напоминания ----------

def test_no_day_reminder_for_booking_made_today(db_session):
    add_booking(db_session, add_contract(db_session), TUE, time(10, 0), created=datetime(2026, 11, 23, 13, 0))
    assert due_reminders(db_session, NOW) == []


async def test_blocked_user_reminder_marked_sent(db_session):
    b = add_booking(db_session, add_contract(db_session), TUE, time(10, 0))
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramForbiddenError(method=SendMessage(chat_id=1, text="x"),
                                                          message="bot was blocked by the user")
    assert await send_reminders(bot) == 0
    db_session.refresh(b)
    assert b.reminder_day_sent  # не повторяем каждые 2 минуты
    bot.send_message.reset_mock()
    await send_reminders(bot)
    bot.send_message.assert_not_called()


async def test_network_error_reminder_retried(db_session):
    b = add_booking(db_session, add_contract(db_session), TUE, time(10, 0))
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramNetworkError(method=SendMessage(chat_id=1, text="x"), message="timeout")
    await send_reminders(bot)
    db_session.refresh(b)
    assert not b.reminder_day_sent  # повторим при следующей проверке
    bot.send_message.side_effect = None
    assert await send_reminders(bot) == 1


async def test_safe_send_waits_on_rate_limit(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    bot = AsyncMock()
    bot.send_message.side_effect = [
        TelegramRetryAfter(method=SendMessage(chat_id=1, text="x"), message="flood", retry_after=3),
        None,
    ]
    assert await safe_send(bot, 1, "hi") is True
    assert bot.send_message.call_count == 2


# ---------- импорт договоров терпим к кривым ячейкам ----------

def test_import_tolerates_bad_cells(db_session, tmp_path):
    path = tmp_path / "c.xlsx"
    pd.DataFrame({
        "Название дома": ["A", "A", "A"],
        "Номер квартиры": [1, 2, 3],
        "Подъезд": [1, 1, 1],
        "Этаж": ["цоколь", 5, 6],
        "Номер договора": [12345, "777-GHP", "888-GHP"],      # число без суффикса из Excel
        "ФИО клиента": ["X", "Y", "Z"],
        "Дата сдачи": ["01.12.2026", "вчера", None],
    }).to_excel(path, index=False)
    r = import_contracts(db_session, str(path))
    assert r.added == 3 and len(r.warnings) == 2
    assert db_session.query(Contract).filter_by(contract_num="12345").one().floor is None   # не «12345.0»
    assert db_session.query(Contract).filter_by(contract_num="777-GHP").one().delivery_date is None


async def test_upload_garbage_file(db_session, monkeypatch):
    monkeypatch.setattr(admin_handlers, "download_document", AsyncMock(return_value=BytesIO(b"not an excel")))
    adm = Client(make_dispatcher(), user_id=ADMIN)
    await adm.text(ADMIN_BUTTONS["contracts"])
    assert "Ничего не изменено" in texts(await send_document(adm))[0]
    await adm.text(ADMIN_BUTTONS["holidays"])
    assert "Список не изменён" in texts(await send_document(adm))[0]


# ---------- двойное нажатие и гонки ----------

async def test_double_tap_confirm_creates_one_booking(db_session):
    """Клиент дважды быстро жмёт «использовать сохранённый номер» — апдейты обрабатываются параллельно."""
    monkey_now = tashkent(2026, 11, 23, 11, 0)
    booking_time.now_tashkent = lambda: monkey_now
    add_contract(db_session, owner=None)
    db_session.add(UserSettings(telegram_id=CLIENT, language="ru", phone="+998977777777"))
    db_session.commit()
    tg = Client(make_dispatcher(), user_id=CLIENT, slow=True)
    await tg.text(CLIENT_BUTTONS["book"]["ru"])
    await tg.text("1-GHP")
    await tg.press("cal:day:2026-11-24")
    await tg.press("slot:pick:1000")
    await tg.press("topic:skip")
    await asyncio.gather(tg.press("phone:saved"), tg.press("phone:saved"))
    assert db_session.query(Booking).count() == 1


async def test_two_clients_same_slot_last_step(db_session):
    """Два клиента одновременно подтверждают один и тот же слот — запись получает один."""
    booking_time.now_tashkent = lambda: tashkent(2026, 11, 23, 11, 0)
    dp = make_dispatcher()
    a, b = Client(dp, user_id=CLIENT, slow=True), Client(dp, user_id=OTHER, slow=True)
    for tg, num in ((a, "1-GHP"), (b, "2-GHP")):
        add_contract(db_session, num, owner=None)
        await tg.text(CLIENT_BUTTONS["book"]["ru"])
        await tg.text(num)
        await tg.press("cal:day:2026-11-24")
        await tg.press("slot:pick:1000")
        await tg.press("topic:skip")
    ra, rb = await asyncio.gather(a.text("+998901111111"), b.text("+998902222222"))
    outcomes = sorted(("Вы записаны" in t) for t in (texts(ra, CLIENT)[0], texts(rb, OTHER)[0]))
    assert outcomes == [False, True]
    assert db_session.query(Booking).count() == 1


# ---------- админ: повторная отрисовка дня не роняет хендлер ----------

async def test_admin_same_day_twice_no_error(db_session):
    adm = Client(make_dispatcher(), user_id=ADMIN)
    await adm.press("sch:day:2026-11-24")
    reqs = await adm.press("sch:day:2026-11-24")
    assert not [a for a in alerts(reqs) if "пошло не так" in (a.text or "")]


# ---------- запуск без ADMIN_ID ----------

def test_refuses_to_start_without_admin_id(tmp_path):
    env = {**os.environ, "BOT_TOKEN": "42:TEST", "ADMIN_ID": "", "DATABASE_URL": f"sqlite:///{tmp_path}/x.db"}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run([sys.executable, "main.py"], cwd=root, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=60)
    assert proc.returncode != 0 and "ADMIN_ID" in proc.stderr
