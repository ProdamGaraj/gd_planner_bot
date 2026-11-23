"""Нет отметки явки за 12 ч после начала встречи — считаем, что клиент пришёл."""
from datetime import date, datetime, time
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from database.models import AttendancePrompt, Booking, Contract
from keyboards.reply import ADMIN_BUTTONS
from services import booking_time
from services.attendance import (
    AUTO_MARK_NAME, AttCb, auto_confirm_attendance, due_auto_confirm, mark_attendance, send_attendance_prompts,
)
from services.booking import no_show_ban
from tests.conftest import tashkent
from tests.harness import Client, alerts, documents, edits, make_dispatcher, texts

ADMIN, CLIENT = 1, 100
MON = date(2026, 11, 23)


def set_now(monkeypatch, *args):
    now = tashkent(*args)
    monkeypatch.setattr(booking_time, "now_tashkent", lambda: now)
    return now


def add_meeting(session, t=time(10, 0), d=MON, num="1-GHP", cancelled=False):
    c = Contract(house_name="A", contract_num=num, client_fio="Иванов", apt_num="1", telegram_id=CLIENT)
    session.add(c)
    session.commit()
    b = Booking(contract_id=c.id, user_telegram_id=CLIENT, date=d, time_slot=t, client_phone="+998",
                created_at=datetime(2026, 11, 1), is_cancelled=cancelled)
    session.add(b)
    session.commit()
    return b


def fake_bot():
    bot = AsyncMock()
    counter = iter(range(500, 10_000))
    bot.send_message.side_effect = lambda *a, **k: MagicMock(message_id=next(counter))
    return bot


def test_exactly_12_hours_after_start(db_session, monkeypatch):
    b = add_meeting(db_session, time(10, 0))
    assert due_auto_confirm(db_session, set_now(monkeypatch, 2026, 11, 23, 21, 59)) == []
    assert [x.id for x in due_auto_confirm(db_session, set_now(monkeypatch, 2026, 11, 23, 22, 0))] == [b.id]


def test_evening_meeting_rolls_to_next_day(db_session, monkeypatch):
    b = add_meeting(db_session, time(17, 30))
    assert due_auto_confirm(db_session, set_now(monkeypatch, 2026, 11, 24, 5, 29)) == []
    assert [x.id for x in due_auto_confirm(db_session, set_now(monkeypatch, 2026, 11, 24, 5, 30))] == [b.id]


def test_skips_marked_and_cancelled(db_session, monkeypatch):
    set_now(monkeypatch, 2026, 11, 23, 11, 0)
    marked = add_meeting(db_session, num="1-GHP")
    mark_attendance(db_session, marked.id, "no_show", ADMIN, "Админ")
    add_meeting(db_session, num="2-GHP", cancelled=True)
    assert due_auto_confirm(db_session, set_now(monkeypatch, 2026, 11, 24, 12, 0)) == []


async def test_auto_confirm_marks_came_and_updates_admins(db_session, monkeypatch):
    set_now(monkeypatch, 2026, 11, 23, 10, 1)
    b = add_meeting(db_session)
    await send_attendance_prompts(fake_bot())
    prompt = db_session.query(AttendancePrompt).one()

    set_now(monkeypatch, 2026, 11, 23, 22, 5)
    bot = AsyncMock()
    assert await auto_confirm_attendance(bot) == 1
    db_session.refresh(b)
    assert (b.attendance, b.attendance_by, b.attendance_by_name) == ("came", None, AUTO_MARK_NAME)
    assert no_show_ban(db_session, b.contract_id) is None  # пришёл — бана нет

    kwargs = bot.edit_message_text.call_args.kwargs
    assert (kwargs["chat_id"], kwargs["message_id"]) == (prompt.chat_id, prompt.message_id)
    assert "автоматически (за 12 ч никто не отметил)" in kwargs["text"]
    assert await auto_confirm_attendance(bot) == 0  # повторно не трогаем


async def test_old_unprompted_meetings_also_confirmed(db_session, monkeypatch):
    """Бот был выключен — запрос не уходил, но через 12 ч встреча всё равно считается состоявшейся."""
    add_meeting(db_session, d=date(2026, 11, 2))
    set_now(monkeypatch, 2026, 11, 23, 9, 0)
    assert await auto_confirm_attendance(AsyncMock()) == 1


async def test_admin_can_still_correct_to_no_show(db_session, monkeypatch):
    b = add_meeting(db_session)
    set_now(monkeypatch, 2026, 11, 23, 22, 30)
    await auto_confirm_attendance(AsyncMock())

    adm = Client(make_dispatcher(), user_id=ADMIN)
    reqs = await adm.press(AttCb(action="no_show", booking_id=b.id).pack())
    assert "Уже отмечено: ✅ Пришёл (автоматически)" in alerts(reqs)[0].text
    await adm.press(AttCb(action="fix", booking_id=b.id).pack())
    await adm.press(AttCb(action="no_show", booking_id=b.id, force=True).pack())
    db_session.refresh(b)
    assert (b.attendance, b.attendance_by) == ("no_show", ADMIN)
    assert no_show_ban(db_session, b.contract_id) == (MON, date(2026, 11, 30))


async def test_report_and_card_show_auto(db_session, monkeypatch):
    add_meeting(db_session)
    set_now(monkeypatch, 2026, 11, 24, 9, 0)
    await auto_confirm_attendance(AsyncMock())
    adm = Client(make_dispatcher(), user_id=ADMIN)

    df = pd.read_excel(BytesIO(documents(await adm.text(ADMIN_BUTTONS["report"]))[0].document.data))
    assert (df.loc[0, "Явка"], df.loc[0, "Явку отметил"]) == ("Пришёл", "автоматически")

    await adm.text(ADMIN_BUTTONS["lookup"])
    assert "явка: ✅ Пришёл (авто)" in texts(await adm.text("1-GHP"))[0]


async def test_manual_mark_within_12h_wins(db_session, monkeypatch):
    b = add_meeting(db_session)
    set_now(monkeypatch, 2026, 11, 23, 10, 15)
    await Client(make_dispatcher(), user_id=ADMIN).press(AttCb(action="no_show", booking_id=b.id).pack())
    set_now(monkeypatch, 2026, 11, 24, 10, 0)
    assert await auto_confirm_attendance(AsyncMock()) == 0
    db_session.refresh(b)
    assert b.attendance == "no_show"
