from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest

from database.models import BlockedSlot, Booking, Contract, Holiday, UserSettings
from keyboards.reply import CLIENT_BUTTONS
from services import booking_time
from services.availability import DayStatus, month_status, slot_map
from services.booking import BookingError, client_earliest_date, create_booking
from services.excel import import_contracts
from services.schedule import TIME_SLOTS
from services.settings import set_cooldown_days
from tests.conftest import tashkent
from tests.harness import Client, alerts, buttons, edits, locations, make_dispatcher, sent, texts

CLIENT, OTHER, ADMIN = 100, 200, 1
NOW = tashkent(2026, 11, 23, 11, 0)  # Пн до 12:00 → ближайшая дата Вт 24.11
MON, TUE, WED, SAT = date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25), date(2026, 11, 28)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(booking_time, "now_tashkent", lambda: NOW)


def add_contract(session, num="12345-MD", owner=None, house="Mahal D"):
    c = Contract(house_name=house, contract_num=num, client_fio="Иванов Иван", apt_num="7",
                 entrance="2", floor=4, telegram_id=owner)
    session.add(c)
    session.commit()
    return c


def add_booking(session, contract, d, t, creator=CLIENT, cancelled=False):
    b = Booking(contract_id=contract.id, user_telegram_id=creator, date=d, time_slot=t,
                client_phone="+998900000000", created_at=datetime(2026, 11, 1), is_cancelled=cancelled)
    session.add(b)
    session.commit()
    return b


def book(session, contract, day=TUE, slot=time(10, 0), user=CLIENT):
    return create_booking(session, contract_id=contract.id, telegram_id=user, username="client",
                          day=day, slot=slot, phone="+998901234567", topic=None)


# ===================== сервис: правила записи =====================

def test_create_booking_binds_contract(db_session):
    c = add_contract(db_session)
    info = book(db_session, c)
    db_session.refresh(c)
    assert c.telegram_id == CLIENT and c.username == "client" and c.href == "https://t.me/client"
    assert (info.date, info.time_slot, info.owner_tg_id) == (TUE, time(10, 0), CLIENT)


@pytest.mark.parametrize("day", [
    MON,                              # раньше минимальной даты
    SAT,                              # выходной
    MON + timedelta(days=61),         # за горизонтом записи (60 дней)
])
def test_create_booking_date_unavailable(db_session, day):
    with pytest.raises(BookingError) as e:
        book(db_session, add_contract(db_session), day=day)
    assert e.value.code == BookingError.DATE_UNAVAILABLE


def test_holiday_and_closed_day_unavailable(db_session):
    db_session.add_all([Holiday(date=TUE), BlockedSlot(date=WED, time_slot=None)])
    db_session.commit()
    c = add_contract(db_session)
    for day in (TUE, WED):
        with pytest.raises(BookingError) as e:
            book(db_session, c, day=day)
        assert e.value.code == BookingError.DATE_UNAVAILABLE


def test_slot_not_in_template_or_blocked(db_session):
    db_session.add(BlockedSlot(date=TUE, time_slot=time(10, 30)))
    db_session.commit()
    c = add_contract(db_session)
    for slot in (time(9, 0), time(12, 30), time(10, 30)):
        with pytest.raises(BookingError) as e:
            book(db_session, c, slot=slot)
        assert e.value.code == BookingError.SLOT_TAKEN


def test_one_client_per_slot(db_session):
    book(db_session, add_contract(db_session, "1-MD"))
    with pytest.raises(BookingError) as e:
        book(db_session, add_contract(db_session, "2-MD"), user=OTHER)
    assert e.value.code == BookingError.SLOT_TAKEN


def test_contract_bound_to_other_account(db_session):
    with pytest.raises(BookingError) as e:
        book(db_session, add_contract(db_session, owner=OTHER))
    assert e.value.code == BookingError.CONTRACT_UNAVAILABLE


def test_any_project_contract_allowed(db_session):
    assert book(db_session, add_contract(db_session, house="Джами")).house_name == "Джами"


def test_one_active_meeting_per_contract(db_session):
    c = add_contract(db_session)
    book(db_session, c)
    with pytest.raises(BookingError) as e:
        book(db_session, c, day=WED)
    assert e.value.code == BookingError.HAS_ACTIVE


def test_cooldown_from_last_meeting(db_session):
    c = add_contract(db_session, owner=CLIENT)
    add_booking(db_session, c, date(2026, 11, 20), time(10, 0))  # прошедшая встреча в пятницу
    assert client_earliest_date(db_session, c.id, CLIENT) == date(2026, 11, 27)  # +7 дней
    set_cooldown_days(db_session, 14)
    assert client_earliest_date(db_session, c.id, CLIENT) == date(2026, 12, 4)
    set_cooldown_days(db_session, 0)
    assert client_earliest_date(db_session, c.id, CLIENT) == TUE


def test_cancelled_meeting_does_not_start_cooldown(db_session):
    c = add_contract(db_session, owner=CLIENT)
    add_booking(db_session, c, date(2026, 11, 20), time(10, 0), cancelled=True)
    assert client_earliest_date(db_session, c.id, CLIENT) == TUE


# ===================== доступность =====================

def test_month_status(db_session):
    for i, slot in enumerate(TIME_SLOTS):  # весь вторник занят
        add_booking(db_session, add_contract(db_session, f"X-{i}"), TUE, slot)
    db_session.add(BlockedSlot(date=WED, time_slot=None))
    db_session.commit()

    st = month_status(db_session, 2026, 11, earliest=TUE)
    assert st[MON] is DayStatus.OFF       # раньше минимальной даты
    assert st[TUE] is DayStatus.FULL
    assert st[WED] is DayStatus.OFF       # закрыт админом
    assert st[date(2026, 11, 26)] is DayStatus.FREE
    assert st[SAT] is DayStatus.OFF


def test_slot_map_marks_booked_and_blocked(db_session):
    add_booking(db_session, add_contract(db_session), TUE, time(10, 0))
    db_session.add(BlockedSlot(date=TUE, time_slot=time(17, 30)))
    db_session.commit()
    m = slot_map(db_session, TUE)
    assert [t for t, free in m.items() if not free] == [time(10, 0), time(17, 30)]


# ===================== импорт договоров =====================

def test_import_contracts_all_houses(db_session, tmp_path):
    path = tmp_path / "c.xlsx"
    pd.DataFrame({
        "Название дома": ["Mahal D", "mahal d ", "Джами", "Mahal D"],
        "Номер квартиры": [1.0, 2, 3, 4],
        "Подъезд": [1, 1, 1, 1],
        "Этаж": [2.0, 3, 4, 5],
        "Номер договора": ["111 md", "222-MD", "333-GHP", None],
        "ФИО клиента": ["А", "Б", "В", "Г"],
        "Дата сдачи": ["01.12.2026", None, "01.12.2026", None],
    }).to_excel(path, index=False)

    r = import_contracts(db_session, str(path))
    assert (r.added, r.updated, r.empty) == (3, 0, 1)
    assert db_session.query(Contract).filter_by(contract_num="333-GHP").one().house_name == "Джами"
    c = db_session.query(Contract).filter_by(contract_num="111MD").one()
    assert (c.apt_num, c.floor, c.delivery_date) == ("1", 2, date(2026, 12, 1))

    c.telegram_id = CLIENT
    db_session.commit()
    r = import_contracts(db_session, str(path))
    assert (r.added, r.updated) == (0, 3)
    db_session.refresh(c)
    assert c.telegram_id == CLIENT  # привязку импорт не трогает


# ===================== сценарий в Telegram =====================

@pytest.fixture
def tg(db_session):
    return Client(make_dispatcher(), user_id=CLIENT)


async def start_to_calendar(tg, contract_num="12345-MD"):
    await tg.text(CLIENT_BUTTONS["book"]["ru"])
    return await tg.text(f"  {contract_num.lower()} ")


async def test_full_booking_flow(db_session, tg):
    add_contract(db_session)

    reqs = await start_to_calendar(tg)
    msgs = sent(reqs)
    assert "Договор подтверждён: Иванов Иван" in msgs[0].text
    assert "Ближайшая доступная дата: 24.11.2026" in msgs[1].text
    cal = buttons(msgs[1].reply_markup)
    assert ("24", "cal:day:2026-11-24") in cal
    assert ("23", "cal:day:2026-11-23") not in cal  # сегодня записаться нельзя

    reqs = await tg.press("cal:day:2026-11-24")
    slots = buttons(edits(reqs)[0].reply_markup)
    assert ("✅ 10:00", "slot:pick:1000") in slots and ("✅ 17:30", "slot:pick:1730") in slots

    reqs = await tg.press("slot:pick:1000")
    assert "Выбрано: 24.11.2026 в 10:00" in edits(reqs)[0].text
    assert "тему встречи" in texts(reqs)[0]

    reqs = await tg.text("Обсудить отделку квартиры")
    assert "Отправьте номер телефона" in texts(reqs)[0]

    reqs = await tg.text("+998 90 123-45-67")
    confirmation = texts(reqs, CLIENT)[0]
    assert "Вы записаны" in confirmation and "10:00" in confirmation and "Обсудить отделку" in confirmation
    assert locations(reqs)
    staff = texts(reqs, ADMIN)
    assert staff and "Новая встреча с CEO" in staff[0] and "12345-MD" in staff[0]

    b = db_session.query(Booking).one()
    assert (b.date, b.time_slot, b.topic, b.client_phone) == (TUE, time(10, 0), "Обсудить отделку квартиры", "+998901234567")
    assert db_session.get(UserSettings, CLIENT).phone == "+998901234567"


async def test_contract_errors(db_session, tg):
    add_contract(db_session, "2-MD", owner=OTHER)
    await tg.text(CLIENT_BUTTONS["book"]["ru"])
    assert "привязан к другому" in texts(await tg.text("2-MD"))[0]
    assert "не найден" in texts(await tg.text("nonsense"))[0]  # всё ещё ждём договор


async def test_existing_meeting_blocks_new_booking(db_session, tg):
    c = add_contract(db_session, owner=CLIENT)
    add_booking(db_session, c, WED, time(16, 0))
    reply = texts(await start_to_calendar(tg))[0]
    assert "уже есть встреча 25.11.2026 в 16:00" in reply


async def test_slot_taken_while_entering_phone(db_session, tg):
    add_contract(db_session)
    await start_to_calendar(tg)
    await tg.press("cal:day:2026-11-24")
    await tg.press("slot:pick:1000")
    await tg.press("topic:skip")
    # Пока клиент вводил телефон, слот занял другой
    add_booking(db_session, add_contract(db_session, "9-MD", owner=OTHER), TUE, time(10, 0), creator=OTHER)

    reqs = await tg.text("+998901234567")
    msgs = sent(reqs)
    assert "только что заняли" in msgs[0].text
    assert ("❌ 10:00", "slot:taken:") in buttons(msgs[1].reply_markup)
    # Клиент выбирает другое время и завершает запись
    await tg.press("slot:pick:1030")
    await tg.press("topic:skip")
    reqs = await tg.text("+998901234567")
    assert "Вы записаны" in texts(reqs, CLIENT)[0]


async def test_saved_phone_offered(db_session, tg):
    add_contract(db_session)
    db_session.add(UserSettings(telegram_id=CLIENT, language="ru", phone="+998977777777"))
    db_session.commit()
    await start_to_calendar(tg)
    await tg.press("cal:day:2026-11-24")
    await tg.press("slot:pick:1100")
    reqs = await tg.press("topic:skip")
    assert ("📱 Использовать +998977777777", "phone:saved") in buttons(sent(reqs)[0].reply_markup)

    reqs = await tg.press("phone:saved")
    assert "Вы записаны" in texts(reqs, CLIENT)[0]
    assert db_session.query(Booking).one().client_phone == "+998977777777"


async def test_language_switch_keeps_step(db_session, tg):
    add_contract(db_session)
    await start_to_calendar(tg)
    reqs = await tg.text(CLIENT_BUTTONS["language"]["ru"])
    msgs = texts(reqs)
    assert "o'zbek" in msgs[0].lower()
    assert "Uchrashuv sanasini tanlang" in msgs[1]
    # Шаг сохранился — выбор даты работает
    assert edits(await tg.press("cal:day:2026-11-24"))


async def test_full_day_and_taken_slot_alerts(db_session, tg):
    add_contract(db_session)
    add_booking(db_session, add_contract(db_session, "9-MD", owner=OTHER), TUE, time(10, 0), creator=OTHER)
    await start_to_calendar(tg)
    await tg.press("cal:day:2026-11-24")
    assert "занято" in alerts(await tg.press("slot:taken:"))[0].text


async def test_topic_validation(db_session, tg):
    add_contract(db_session)
    await start_to_calendar(tg)
    await tg.press("cal:day:2026-11-24")
    await tg.press("slot:pick:1000")
    assert "Слишком длинно" in texts(await tg.text("x" * 301))[0]


async def test_invalid_phone_then_contact(db_session, tg):
    add_contract(db_session)
    await start_to_calendar(tg)
    await tg.press("cal:day:2026-11-24")
    await tg.press("slot:pick:1000")
    await tg.press("topic:skip")
    assert "Допускаются только" in texts(await tg.text("12345"))[0]
    reqs = await tg.contact("998901112233")
    assert "Вы записаны" in texts(reqs, CLIENT)[0]


async def test_calendar_navigation_bounded(db_session, tg):
    add_contract(db_session)
    reqs = await start_to_calendar(tg)
    nav = buttons(sent(reqs)[1].reply_markup)[-2:]
    assert nav[0][1] == "cal:noop:"            # назад нельзя — это месяц минимальной даты
    assert nav[1][1] == "cal:nav:2026-12"
    reqs = await tg.press("cal:nav:2026-12")
    assert "Декабрь 2026" in buttons(edits(reqs)[0].reply_markup)[0][0]
    # Горизонт 60 дней (до 22.01.2027) — в феврале листать нельзя
    reqs = await tg.press("cal:nav:2027-02")
    assert "Январь 2027" in buttons(edits(reqs)[0].reply_markup)[0][0]


# ===================== Ввод номера договора =====================

@pytest.mark.parametrize("typed", ["13791-GHP", " 13791-ghp ", "13791", "13791GHP", "13791 ghp", "1 3 7 9 1"])
def test_find_contract_forgiving_input(db_session, typed):
    from services.booking import find_contract
    add_contract(db_session, "13791-GHP")
    assert find_contract(db_session, typed).contract_num == "13791-GHP"


def test_find_contract_ambiguous_or_wrong(db_session):
    from services.booking import find_contract
    add_contract(db_session, "13791-GHP")
    add_contract(db_session, "13791-XYZ")
    add_contract(db_session, "137910-GHP")
    assert find_contract(db_session, "13791") is None        # два договора с таким номером — нужен полный
    assert find_contract(db_session, "13791-XYZ").contract_num == "13791-XYZ"
    assert find_contract(db_session, "1379") is None          # префикс номера не подходит
    assert find_contract(db_session, "%") is None
    assert find_contract(db_session, "") is None


async def test_booking_with_number_without_suffix(db_session, tg):
    add_contract(db_session, "13791-GHP")
    await tg.text(CLIENT_BUTTONS["book"]["ru"])
    assert "Договор подтверждён" in texts(await tg.text("13791"))[0]
