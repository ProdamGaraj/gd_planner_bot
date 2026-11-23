"""Бан за неявку: следующая встреча не раньше даты пропущенной + N дней (по умолчанию 7)."""
from datetime import date, datetime, time

import pytest

from database.models import Booking, Contract
from keyboards.reply import ADMIN_BUTTONS, CLIENT_BUTTONS
from services import booking_time
from services.attendance import AttCb, mark_attendance
from services.booking import BookingError, client_earliest_date, create_booking, no_show_ban, reschedule_booking
from services.settings import get_no_show_ban_days, set_cooldown_days, set_no_show_ban_days
from tests.conftest import tashkent
from tests.harness import Client, buttons, edits, make_dispatcher, sent, texts

CLIENT, OTHER, ADMIN = 100, 200, 1
MON = date(2026, 11, 23)
NEXT_MON = date(2026, 11, 30)
NOW = tashkent(2026, 11, 23, 16, 0)  # Пн 16:00: обычная минимальная дата — Ср 25.11


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(booking_time, "now_tashkent", lambda: NOW)


@pytest.fixture
def missed(db_session):
    """Договор клиента с пропущенной сегодня встречей (10:00, отмечено «не пришёл»). Кулдаун выключен,
    чтобы проверять именно бан."""
    set_cooldown_days(db_session, 0)
    c = Contract(house_name="ОзМахал-D 8", contract_num="1-GHP", client_fio="Иванов", apt_num="1", telegram_id=CLIENT)
    db_session.add(c)
    db_session.commit()
    b = Booking(contract_id=c.id, user_telegram_id=CLIENT, date=MON, time_slot=time(10, 0),
                client_phone="+998901234567", created_at=datetime(2026, 11, 1))
    db_session.add(b)
    db_session.commit()
    mark_attendance(db_session, b.id, "no_show", ADMIN, "Админ")
    return c, b


def test_default_is_week(db_session):
    assert get_no_show_ban_days(db_session) == 7


def test_ban_pushes_earliest_date(db_session, missed):
    c, _ = missed
    assert no_show_ban(db_session, c.id) == (MON, NEXT_MON)
    assert client_earliest_date(db_session, c.id, CLIENT) == NEXT_MON  # без бана было бы 25.11


def test_ban_length_setting(db_session, missed):
    c, _ = missed
    set_no_show_ban_days(db_session, 14)
    assert client_earliest_date(db_session, c.id, CLIENT) == date(2026, 12, 7)
    set_no_show_ban_days(db_session, 0)
    assert no_show_ban(db_session, c.id) is None
    assert client_earliest_date(db_session, c.id, CLIENT) == date(2026, 11, 25)
    with pytest.raises(ValueError):
        set_no_show_ban_days(db_session, -1)


def test_ban_and_cooldown_take_the_later_date(db_session, missed):
    c, _ = missed
    set_cooldown_days(db_session, 10)
    assert client_earliest_date(db_session, c.id, CLIENT) == date(2026, 12, 3)  # кулдаун дальше бана
    set_cooldown_days(db_session, 3)
    assert client_earliest_date(db_session, c.id, CLIENT) == NEXT_MON         # бан дальше кулдауна


def test_ban_follows_contract_not_account(db_session, missed):
    c, _ = missed
    c.telegram_id = OTHER  # админ перепривязал договор
    db_session.commit()
    assert client_earliest_date(db_session, c.id, OTHER) == NEXT_MON


def test_correcting_mark_lifts_ban(db_session, missed):
    c, b = missed
    mark_attendance(db_session, b.id, "came", ADMIN, "Админ", force=True)
    assert no_show_ban(db_session, c.id) is None


def test_ban_expires(db_session, missed, monkeypatch):
    c, _ = missed
    monkeypatch.setattr(booking_time, "now_tashkent", lambda: tashkent(2026, 11, 30, 9, 0))
    assert no_show_ban(db_session, c.id) is None


def test_crafted_booking_inside_ban_rejected(db_session, missed):
    c, _ = missed
    with pytest.raises(BookingError) as e:
        create_booking(db_session, contract_id=c.id, telegram_id=CLIENT, username=None, day=date(2026, 11, 26),
                       slot=time(10, 0), phone="+998901234567", topic=None)
    assert e.value.code == BookingError.DATE_UNAVAILABLE
    assert create_booking(db_session, contract_id=c.id, telegram_id=CLIENT, username=None, day=NEXT_MON,
                          slot=time(10, 0), phone="+998901234567", topic=None).date == NEXT_MON


def test_reschedule_respects_ban(db_session, missed):
    c, _ = missed
    future = Booking(contract_id=c.id, user_telegram_id=CLIENT, date=date(2026, 12, 2), time_slot=time(10, 0),
                     client_phone="+998", created_at=datetime(2026, 11, 20))
    db_session.add(future)
    db_session.commit()
    with pytest.raises(BookingError) as e:
        reschedule_booking(db_session, booking_id=future.id, telegram_id=CLIENT, username=None,
                           day=date(2026, 11, 26), slot=time(11, 0))
    assert e.value.code == BookingError.DATE_UNAVAILABLE


# ===================== что видят клиент и админ =====================

async def test_client_sees_ban_notice_and_calendar_starts_later(db_session, missed):
    tg = Client(make_dispatcher(), user_id=CLIENT)
    await tg.text(CLIENT_BUTTONS["book"]["ru"])
    reqs = await tg.text("1-GHP")
    msgs = texts(reqs)
    assert "Вы не пришли на встречу 23.11.2026" in msgs[1] and "не раньше 30.11.2026" in msgs[1]
    cal = buttons(sent(reqs)[-1].reply_markup)
    assert ("30", "cal:day:2026-11-30") in cal
    assert not [cb for _, cb in cal if cb in ("cal:day:2026-11-25", "cal:day:2026-11-27")]


async def test_client_uzbek_notice(db_session, missed):
    from services.users import set_user_language
    set_user_language(db_session, CLIENT, "uz")
    tg = Client(make_dispatcher(), user_id=CLIENT)
    await tg.text(CLIENT_BUTTONS["book"]["uz"])
    assert "uchrashuvga kelmadingiz" in texts(await tg.text("1-GHP"))[1]


async def test_no_notice_without_ban(db_session, missed):
    c, b = missed
    mark_attendance(db_session, b.id, "came", ADMIN, "Админ", force=True)
    tg = Client(make_dispatcher(), user_id=CLIENT)
    await tg.text(CLIENT_BUTTONS["book"]["ru"])
    assert not [t for t in texts(await tg.text("1-GHP")) if "не пришли" in t]


async def test_admin_mark_shows_ban_date(db_session):
    set_cooldown_days(db_session, 0)
    c = Contract(house_name="A", contract_num="2-GHP", client_fio="Петров", telegram_id=CLIENT)
    db_session.add(c)
    db_session.commit()
    b = Booking(contract_id=c.id, user_telegram_id=CLIENT, date=MON, time_slot=time(10, 0),
                client_phone="+998", created_at=datetime(2026, 11, 1))
    db_session.add(b)
    db_session.commit()
    reqs = await Client(make_dispatcher(), user_id=ADMIN).press(AttCb(action="no_show", booking_id=b.id).pack())
    assert "Бан за неявку: клиент сможет записаться не раньше 30.11.2026" in edits(reqs)[0].text


async def test_admin_settings_and_card(db_session, missed):
    adm = Client(make_dispatcher(), user_id=ADMIN)
    assert "Бан за неявку: <b>7</b>" in texts(await adm.text(ADMIN_BUTTONS["settings"]))[0]
    await adm.press("adm:noshow_ban:")
    assert "целое число" in texts(await adm.text("abc"))[0]
    assert "Бан за неявку: 14" in texts(await adm.text("14"))[0]
    assert get_no_show_ban_days(db_session) == 14

    await adm.text(ADMIN_BUTTONS["lookup"])
    card = texts(await adm.text("1-GHP"))[0]
    assert "⛔ Неявка 23.11.2026 — запись не раньше 07.12.2026" in card
