"""Отметка явки: запрос админам в начале встречи, кнопки «Пришёл» / «Не пришёл»."""
import asyncio
import sqlite3
from datetime import date, datetime, time
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from aiogram.methods import EditMessageText
from sqlalchemy import create_engine

from database.models import AttendancePrompt, Booking, Contract, Staff
from database.session import add_missing_columns
from keyboards.reply import ADMIN_BUTTONS
from services import booking_time
from services.attendance import AttCb, due_prompts, send_attendance_prompts
from tests.conftest import tashkent
from tests.harness import Client, alerts, buttons, documents, edits, make_dispatcher, sent, texts

ADMIN, ADMIN2, EMPLOYEE, CLIENT = 1, 2, 10, 100
MON = date(2026, 11, 23)
NOW = tashkent(2026, 11, 23, 10, 31)  # встреча в 10:30 только что началась


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(booking_time, "now_tashkent", lambda: NOW)


def add_meeting(session, t=time(10, 30), d=MON, num="1-GHP", cancelled=False):
    c = Contract(house_name="ОзМахал-D 8", contract_num=num, client_fio="Иванов Иван", apt_num="12",
                 telegram_id=CLIENT, username="ivanov")
    session.add(c)
    session.commit()
    b = Booking(contract_id=c.id, user_telegram_id=CLIENT, date=d, time_slot=t, client_phone="+998901234567",
                topic="Отделка", created_at=datetime(2026, 11, 1), is_cancelled=cancelled)
    session.add(b)
    session.commit()
    return b


def add_staff(session):
    session.add_all([Staff(telegram_id=ADMIN2, role="admin"), Staff(telegram_id=EMPLOYEE, role="employee")])
    session.commit()


def cb(action, booking_id, force=False):
    return AttCb(action=action, booking_id=booking_id, force=force).pack()


def fake_bot():
    bot = AsyncMock()
    counter = iter(range(500, 10_000))
    bot.send_message.side_effect = lambda *a, **k: MagicMock(message_id=next(counter))
    return bot


# ===================== кому и когда =====================

def test_due_prompts_only_started_today(db_session):
    started = add_meeting(db_session, time(10, 30), num="1-GHP")
    add_meeting(db_session, time(11, 0), num="2-GHP")                       # ещё не началась
    add_meeting(db_session, time(10, 0), num="3-GHP", cancelled=True)       # отменена
    add_meeting(db_session, time(10, 0), d=date(2026, 11, 20), num="4-GHP")  # прошлый день — не спамим
    assert [b.id for b in due_prompts(db_session, NOW)] == [started.id]


async def test_prompt_sent_to_all_admins_once(db_session):
    add_staff(db_session)
    b = add_meeting(db_session)
    bot = fake_bot()
    assert await send_attendance_prompts(bot) == 1

    recipients = sorted(c.args[0] for c in bot.send_message.call_args_list)
    assert recipients == [ADMIN, ADMIN2]  # сотрудник (не админ) запрос не получает
    text = bot.send_message.call_args.args[1]
    assert "отметьте явку" in text and "Иванов Иван" in text and "10:30" in text
    kb = bot.send_message.call_args.kwargs["reply_markup"]
    assert [x[1] for x in buttons(kb)] == [cb("came", b.id), cb("no_show", b.id)]
    assert db_session.query(AttendancePrompt).filter_by(booking_id=b.id).count() == 2

    bot.send_message.reset_mock()
    assert await send_attendance_prompts(bot) == 0  # повторно не шлём
    bot.send_message.assert_not_called()


async def test_prompt_not_repeated_when_delivery_fails(db_session):
    add_meeting(db_session)
    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError("network down")
    await send_attendance_prompts(bot)
    assert await send_attendance_prompts(bot) == 0


# ===================== отметка =====================

async def prompts_sent(db_session):
    """Разослать запрос и вернуть id встречи и сообщения админов."""
    await send_attendance_prompts(fake_bot())
    return {p.chat_id: p.message_id for p in db_session.query(AttendancePrompt)}


async def test_admin_marks_came_and_other_admins_updated(db_session):
    add_staff(db_session)
    b = add_meeting(db_session)
    msgs = await prompts_sent(db_session)

    adm = Client(make_dispatcher(), user_id=ADMIN)
    reqs = await adm.press(cb("came", b.id))
    assert "✅ Пришёл — отметил(а) T в 10:31" in edits(reqs)[0].text
    assert buttons(edits(reqs)[0].reply_markup)[0][0] == "↩️ Исправить"
    # Сообщение второго админа тоже обновилось, кнопок отметки там больше нет
    others = [r for r in reqs if isinstance(r, EditMessageText) and r.chat_id == ADMIN2]
    assert others and others[0].message_id == msgs[ADMIN2] and "Пришёл" in others[0].text

    db_session.refresh(b)
    assert (b.attendance, b.attendance_by, b.attendance_at) == ("came", ADMIN, datetime(2026, 11, 23, 10, 31))


async def test_second_admin_cannot_silently_overwrite(db_session):
    add_staff(db_session)
    b = add_meeting(db_session)
    dp = make_dispatcher()
    await Client(dp, user_id=ADMIN).press(cb("came", b.id))
    reqs = await Client(dp, user_id=ADMIN2).press(cb("no_show", b.id))  # нажал старую кнопку
    assert "Уже отмечено: ✅ Пришёл" in alerts(reqs)[0].text
    db_session.refresh(b)
    assert b.attendance == "came"


async def test_fix_mark(db_session):
    b = add_meeting(db_session)
    adm = Client(make_dispatcher(), user_id=ADMIN)
    await adm.press(cb("came", b.id))
    reqs = await adm.press(cb("fix", b.id))
    fixed_kb = [r for r in reqs if r.__class__.__name__ == "EditMessageReplyMarkup"][0].reply_markup
    assert [x[1] for x in buttons(fixed_kb)] == [cb("came", b.id, True), cb("no_show", b.id, True)]
    await adm.press(cb("no_show", b.id, True))
    db_session.refresh(b)
    assert b.attendance == "no_show"


async def test_simultaneous_marks_one_wins(db_session):
    add_staff(db_session)
    b = add_meeting(db_session)
    dp = make_dispatcher()
    a1, a2 = Client(dp, user_id=ADMIN, slow=True), Client(dp, user_id=ADMIN2, slow=True)
    await asyncio.gather(a1.press(cb("came", b.id)), a2.press(cb("no_show", b.id)))
    db_session.refresh(b)
    assert b.attendance in ("came", "no_show") and b.attendance_by in (ADMIN, ADMIN2)


@pytest.mark.parametrize("case, alert", [
    ("future", "ещё не началась"),
    ("cancelled", "отменена"),
    ("missing", "не найдена"),
])
async def test_mark_rejected(db_session, case, alert):
    if case == "future":
        bid = add_meeting(db_session, time(16, 0)).id
    elif case == "cancelled":
        bid = add_meeting(db_session, cancelled=True).id
    else:
        bid = 999
    reqs = await Client(make_dispatcher(), user_id=ADMIN).press(cb("came", bid))
    assert alert in alerts(reqs)[0].text


@pytest.mark.parametrize("user_id", [EMPLOYEE, CLIENT])
async def test_only_admins_can_mark(db_session, user_id):
    add_staff(db_session)
    b = add_meeting(db_session)
    reqs = await Client(make_dispatcher(), user_id=user_id).press(cb("came", b.id))
    assert "устарела" in alerts(reqs)[0].text
    db_session.refresh(b)
    assert b.attendance is None


# ===================== отмена идущей встречи, отчёт, карточка =====================

async def test_admin_cancels_ongoing_meeting_prompt_updated(db_session):
    b = add_meeting(db_session)
    await prompts_sent(db_session)
    adm = Client(make_dispatcher(), user_id=ADMIN)
    reqs = await adm.press(f"mt:yes:{b.id}")
    updated = [r for r in reqs if isinstance(r, EditMessageText) and "явка не отмечается" in r.text]
    assert updated and updated[0].reply_markup is None


async def test_report_and_contract_card_show_attendance(db_session):
    b = add_meeting(db_session)
    adm = Client(make_dispatcher(), user_id=ADMIN)
    await adm.press(cb("no_show", b.id))

    doc = documents(await adm.text(ADMIN_BUTTONS["report"]))[0]
    df = pd.read_excel(BytesIO(doc.document.data))
    assert df.loc[0, "Явка"] == "Не пришёл" and df.loc[0, "Явку отметил"] == "T"

    await adm.text(ADMIN_BUTTONS["lookup"])
    card = texts(await adm.text("1-GHP"))[0]
    assert "10:30 — явка: ❌ Не пришёл" in card


# ===================== миграция живой БД =====================

def test_migration_adds_columns_to_old_db(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    # Схема bookings до появления явки
    con.execute("""CREATE TABLE bookings (id INTEGER PRIMARY KEY, contract_id INTEGER NOT NULL,
        user_telegram_id INTEGER, date DATE NOT NULL, time_slot TIME NOT NULL, client_phone VARCHAR,
        topic VARCHAR, created_at DATETIME NOT NULL, reminder_day_sent BOOLEAN NOT NULL,
        reminder_hour_sent BOOLEAN NOT NULL, is_cancelled BOOLEAN NOT NULL, cancelled_by VARCHAR,
        cancelled_at DATETIME)""")
    con.execute("INSERT INTO bookings VALUES (1, 1, 5, '2026-11-24', '10:00:00', '+998', NULL, "
                "'2026-11-20 10:00:00', 0, 0, 0, NULL, NULL)")
    con.commit()
    con.close()

    from database.session import init_db
    engine = create_engine(f"sqlite:///{path}")
    init_db(engine)
    con = sqlite3.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(bookings)")}
    assert {"attendance", "attendance_by", "attendance_by_name", "attendance_at", "attendance_prompted"} <= cols
    assert con.execute("SELECT attendance, attendance_prompted FROM bookings").fetchone() == (None, 0)
    assert add_missing_columns(engine) == []  # повторный запуск ничего не меняет
    engine.dispose()
