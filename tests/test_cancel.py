import asyncio
from datetime import date, datetime, time
from unittest.mock import AsyncMock

import pytest

from database.models import Booking, Contract, Holiday, Staff
from handlers import client as client_handlers
from keyboards.inline import CancelCb
from services import booking_time
from services.booking import (
    CANCELLED_BY_BLOCK, CANCELLED_BY_CLIENT, CANCELLED_BY_HOLIDAY, CancelError,
    cancel_by_client, cancel_by_company, client_active_bookings,
)
from services.notify import notify_clients_company_cancel, notify_staff
from tests.conftest import tashkent

CLIENT = 100
OTHER = 200
# Понедельник 23.11.2026, 11:00 — отменять можно встречи со вторника
NOW = tashkent(2026, 11, 23, 11, 0)
MON, TUE, WED = date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(booking_time, "now_tashkent", lambda: NOW)


def add_contract(session, num="1-MD", owner=CLIENT, username="client"):
    c = Contract(house_name="Mahal D", contract_num=num, client_fio="Иванов Иван",
                 apt_num="12", entrance="1", floor=3, telegram_id=owner, username=username)
    session.add(c)
    session.commit()
    return c


def add_booking(session, contract, d, t, cancelled=False, creator=CLIENT):
    b = Booking(contract_id=contract.id, user_telegram_id=creator, date=d, time_slot=t,
                client_phone="+998901234567", topic="Вопрос по договору",
                created_at=datetime(2026, 11, 20), is_cancelled=cancelled)
    session.add(b)
    session.commit()
    return b


# ================= сервис =================

def test_client_active_bookings_filters(db_session):
    mine = add_contract(db_session, "1-MD")
    other = add_contract(db_session, "2-MD", owner=OTHER)
    past = add_booking(db_session, mine, MON, time(10, 0))           # закончилась в 10:30
    today_later = add_booking(db_session, mine, MON, time(16, 0))
    add_booking(db_session, mine, TUE, time(10, 0), cancelled=True)
    future = add_booking(db_session, mine, WED, time(10, 0))
    add_booking(db_session, other, TUE, time(11, 0), creator=OTHER)

    ids = [b.id for b in client_active_bookings(db_session, CLIENT, NOW)]
    assert ids == [today_later.id, future.id]
    assert past.id not in ids


def test_cancel_by_client_success(db_session):
    b = add_booking(db_session, add_contract(db_session), TUE, time(10, 0))
    info = cancel_by_client(db_session, b.id, CLIENT, NOW)

    db_session.refresh(b)
    assert b.is_cancelled and b.cancelled_by == CANCELLED_BY_CLIENT
    assert b.cancelled_at == datetime(2026, 11, 23, 11, 0)
    assert (info.date_str, info.time_str, info.contract_num) == ("24.11.2026", "10:00", "1-MD")


def test_cancel_too_late(db_session):
    contract = add_contract(db_session)
    b_today = add_booking(db_session, contract, MON, time(17, 0))
    with pytest.raises(CancelError) as e:
        cancel_by_client(db_session, b_today.id, CLIENT, NOW)
    assert e.value.code == CancelError.TOO_LATE

    # После 12:00 вторник уже заблокирован
    b_tue = add_booking(db_session, contract, TUE, time(10, 0))
    with pytest.raises(CancelError) as e:
        cancel_by_client(db_session, b_tue.id, CLIENT, tashkent(2026, 11, 23, 12, 0))
    assert e.value.code == CancelError.TOO_LATE


@pytest.mark.parametrize("case", ["other_owner", "cancelled", "past", "missing"])
def test_cancel_not_found(db_session, case):
    contract = add_contract(db_session)
    if case == "other_owner":
        bid = add_booking(db_session, add_contract(db_session, "2-MD", owner=OTHER), WED, time(10, 0)).id
    elif case == "cancelled":
        bid = add_booking(db_session, contract, WED, time(10, 0), cancelled=True).id
    elif case == "past":
        bid = add_booking(db_session, contract, MON, time(10, 0)).id
    else:
        bid = 999
    with pytest.raises(CancelError) as e:
        cancel_by_client(db_session, bid, CLIENT, NOW)
    assert e.value.code == CancelError.NOT_FOUND


def test_cancel_after_rebind_not_allowed_for_old_account(db_session):
    contract = add_contract(db_session)
    b = add_booking(db_session, contract, WED, time(10, 0))
    contract.telegram_id = OTHER  # админ перепривязал договор
    db_session.commit()
    with pytest.raises(CancelError):
        cancel_by_client(db_session, b.id, CLIENT, NOW)
    assert cancel_by_client(db_session, b.id, OTHER, NOW).owner_tg_id == OTHER


def test_holiday_meeting_cancellable_until_start(db_session):
    contract = add_contract(db_session)
    db_session.add(Holiday(date=MON))
    db_session.commit()
    b = add_booking(db_session, contract, MON, time(16, 0))
    assert cancel_by_client(db_session, b.id, CLIENT, NOW).id == b.id


def test_cancel_by_company(db_session):
    contract = add_contract(db_session)
    b1 = add_booking(db_session, contract, MON, time(16, 0))  # сегодня — компании можно
    b2 = add_booking(db_session, contract, TUE, time(10, 0), cancelled=True)
    infos = cancel_by_company(db_session, [b1.id, b2.id], CANCELLED_BY_BLOCK, NOW)

    assert [i.id for i in infos] == [b1.id]
    db_session.refresh(b1)
    assert b1.cancelled_by == CANCELLED_BY_BLOCK
    with pytest.raises(ValueError):
        cancel_by_company(db_session, [b1.id], "client", NOW)


def test_cancelled_slot_can_be_booked_again(db_session):
    contract = add_contract(db_session)
    b = add_booking(db_session, contract, WED, time(10, 0))
    cancel_by_client(db_session, b.id, CLIENT, NOW)
    other = add_contract(db_session, "2-MD", owner=OTHER)
    add_booking(db_session, other, WED, time(10, 0), creator=OTHER)  # без IntegrityError


# ================= хендлеры =================

def _buttons(markup):
    return [(btn.text, btn.callback_data) for row in markup.inline_keyboard for btn in row]


async def test_cancel_button_no_meetings(db_session, make_message):
    message = make_message(CLIENT)
    await client_handlers.cancel_start(message, AsyncMock())
    assert "нет активных встреч" in message.answer.call_args.args[0]


async def test_cancel_button_lists_meetings_with_locks(db_session, make_message):
    contract = add_contract(db_session)
    locked = add_booking(db_session, contract, MON, time(16, 0))
    open_ = add_booking(db_session, contract, TUE, time(10, 30))
    message = make_message(CLIENT)

    await client_handlers.cancel_start(message, AsyncMock())

    buttons = _buttons(message.answer.call_args.kwargs["reply_markup"])
    assert buttons == [
        ("🔒 23.11.2026 ⏰ 16:00", f"cxl:locked:{locked.id}"),
        ("📅 24.11.2026 ⏰ 10:30", f"cxl:pick:{open_.id}"),
        ("🔙 Назад", "cxl:back:0"),
    ]


async def test_cancel_button_all_locked(db_session, make_message):
    add_booking(db_session, add_contract(db_session), MON, time(16, 0))
    message = make_message(CLIENT)
    await client_handlers.cancel_start(message, AsyncMock())
    text = message.answer.call_args.args[0]
    assert "нельзя отменить" in text and "+998" in text


async def test_full_cancel_flow_notifies_staff(db_session, make_callback, monkeypatch):
    b = add_booking(db_session, add_contract(db_session), TUE, time(10, 0))
    notify = AsyncMock()
    monkeypatch.setattr(client_handlers, "notify_staff", notify)

    pick = make_callback(CLIENT)
    await client_handlers.cancel_pick(pick, CancelCb(action="pick", booking_id=b.id))
    assert "Отменить встречу?" in pick.message.edit_text.call_args.args[0]
    assert _buttons(pick.message.edit_text.call_args.kwargs["reply_markup"])[0][1] == f"cxl:yes:{b.id}"

    yes = make_callback(CLIENT)
    await client_handlers.cancel_confirmed(yes, CancelCb(action="yes", booking_id=b.id), AsyncMock())
    assert "отменена" in yes.message.edit_text.call_args.args[0]

    await asyncio.sleep(0)  # дать фоновой задаче уведомления выполниться
    notify.assert_awaited_once()
    staff_text = notify.call_args.args[1]
    assert "отменена клиентом" in staff_text and "1-MD" in staff_text and "Вопрос по договору" in staff_text

    db_session.refresh(b)
    assert b.is_cancelled


async def test_confirm_twice_shows_not_found(db_session, make_callback, monkeypatch):
    b = add_booking(db_session, add_contract(db_session), TUE, time(10, 0))
    monkeypatch.setattr(client_handlers, "notify_staff", AsyncMock())
    await client_handlers.cancel_confirmed(make_callback(CLIENT), CancelCb(action="yes", booking_id=b.id), AsyncMock())

    again = make_callback(CLIENT)
    await client_handlers.cancel_confirmed(again, CancelCb(action="yes", booking_id=b.id), AsyncMock())
    assert "не найдена" in again.message.edit_text.call_args.args[0]


async def test_foreign_booking_id_rejected(db_session, make_callback):
    b = add_booking(db_session, add_contract(db_session, owner=OTHER), TUE, time(10, 0), creator=OTHER)
    cb = make_callback(CLIENT)
    await client_handlers.cancel_confirmed(cb, CancelCb(action="yes", booking_id=b.id), AsyncMock())
    assert "не найдена" in cb.message.edit_text.call_args.args[0]
    db_session.refresh(b)
    assert not b.is_cancelled


async def test_locked_button_shows_alert(db_session, make_callback):
    cb = make_callback(CLIENT)
    await client_handlers.cancel_locked(cb)
    assert cb.answer.call_args.kwargs["show_alert"] is True


async def test_keep_button(db_session, make_callback):
    cb = make_callback(CLIENT)
    await client_handlers.cancel_aborted(cb)
    assert "без изменений" in cb.message.edit_text.call_args.args[0]


# ================= уведомления =================

async def test_notify_staff_reaches_admin_and_staff(db_session):
    db_session.add_all([Staff(telegram_id=10, role="employee"), Staff(telegram_id=11, role="admin")])
    db_session.commit()
    bot = AsyncMock()
    await notify_staff(bot, "text")
    assert sorted(c.args[0] for c in bot.send_message.call_args_list) == [1, 10, 11]


async def test_notify_clients_company_cancel_uses_language(db_session):
    from services.users import set_user_language
    contract = add_contract(db_session)
    set_user_language(db_session, CLIENT, "uz")
    b = add_booking(db_session, contract, WED, time(10, 0))
    infos = cancel_by_company(db_session, [b.id], CANCELLED_BY_HOLIDAY, NOW)

    bot = AsyncMock()
    assert await notify_clients_company_cancel(bot, infos, CANCELLED_BY_HOLIDAY) == 1
    chat_id, text = bot.send_message.call_args.args
    assert chat_id == CLIENT
    assert "bekor qilindi" in text and "dam olish" in text
