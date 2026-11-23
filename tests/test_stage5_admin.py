"""Мои встречи, перенос, напоминания, админ-панель."""
from datetime import date, datetime, time
from io import BytesIO
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from database.models import BlockedSlot, Booking, Contract, ContractBindingLog, Holiday, Staff
from handlers import admin as admin_handlers
from keyboards.reply import ADMIN_BUTTONS, CLIENT_BUTTONS
from services import booking_time
from services.booking import BookingError, CancelError, reschedule_booking
from services.reminders import due_reminders, send_reminders
from services.settings import get_cooldown_days
from tests.conftest import tashkent
from tests.harness import (
    Client, alerts, buttons, documents, edits, make_dispatcher, send_document, sent, texts,
)

CLIENT, OTHER, ADMIN, EMPLOYEE = 100, 200, 1, 10
NOW = tashkent(2026, 11, 23, 11, 0)  # Пн до 12:00
MON, TUE, WED, THU = date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25), date(2026, 11, 26)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(booking_time, "now_tashkent", lambda: NOW)


def add_contract(session, num="12345-MD", owner=CLIENT):
    c = Contract(house_name="Mahal D", contract_num=num, client_fio="Иванов Иван", apt_num="7",
                 entrance="2", floor=4, telegram_id=owner)
    session.add(c)
    session.commit()
    return c


def add_booking(session, contract, d, t, creator=CLIENT, topic="Тема"):
    b = Booking(contract_id=contract.id, user_telegram_id=creator, date=d, time_slot=t,
                client_phone="+998901234567", topic=topic, created_at=datetime(2026, 11, 1))
    session.add(b)
    session.commit()
    return b


@pytest.fixture
def tg(db_session):
    return Client(make_dispatcher(), user_id=CLIENT)


@pytest.fixture
def adm(db_session):
    return Client(make_dispatcher(), user_id=ADMIN)


# ===================== Мои встречи =====================

async def test_my_meetings(db_session, tg):
    c = add_contract(db_session)
    add_booking(db_session, c, WED, time(16, 30))
    text = texts(await tg.text(CLIENT_BUTTONS["my"]["ru"]))[0]
    assert "25.11.2026 ⏰ 16:30" in text and "12345-MD" in text and "Тема" in text and "Адрес" in text


async def test_my_meetings_empty_uz(db_session, tg):
    from services.users import set_user_language
    set_user_language(db_session, CLIENT, "uz")
    assert "uchrashuvlar yo'q" in texts(await tg.text(CLIENT_BUTTONS["my"]["uz"]))[0]


# ===================== Перенос: сервис =====================

def test_reschedule_service(db_session):
    c = add_contract(db_session)
    old = add_booking(db_session, c, WED, time(10, 0))
    old_info, new_info = reschedule_booking(db_session, booking_id=old.id, telegram_id=CLIENT, username="u",
                                            day=THU, slot=time(16, 0))
    db_session.refresh(old)
    assert old.is_cancelled and old.cancelled_by == "rebook"
    new = db_session.get(Booking, new_info.id)
    assert (new.date, new.time_slot, new.topic, new.client_phone) == (THU, time(16, 0), "Тема", "+998901234567")


def test_reschedule_ignores_own_meeting_for_cooldown(db_session):
    c = add_contract(db_session)
    old = add_booking(db_session, c, WED, time(10, 0))
    # С учётом кулдауна от самой переносимой встречи ближайшая дата была бы 02.12 — исключаем её
    _, new = reschedule_booking(db_session, booking_id=old.id, telegram_id=CLIENT, username=None,
                                day=TUE, slot=time(11, 0))
    assert new.date == TUE


def test_reschedule_too_late_and_taken(db_session):
    c = add_contract(db_session)
    today = add_booking(db_session, c, MON, time(17, 0))
    with pytest.raises(CancelError) as e:
        reschedule_booking(db_session, booking_id=today.id, telegram_id=CLIENT, username=None, day=THU, slot=time(10, 0))
    assert e.value.code == CancelError.TOO_LATE

    c2 = add_contract(db_session, "2-MD")
    b2 = add_booking(db_session, c2, WED, time(10, 0))
    add_booking(db_session, add_contract(db_session, "3-MD", owner=OTHER), THU, time(10, 0), creator=OTHER)
    with pytest.raises(BookingError) as e:
        reschedule_booking(db_session, booking_id=b2.id, telegram_id=CLIENT, username=None, day=THU, slot=time(10, 0))
    assert e.value.code == BookingError.SLOT_TAKEN
    db_session.refresh(b2)
    assert not b2.is_cancelled  # старая встреча осталась


# ===================== Перенос: сценарий =====================

async def test_reschedule_flow(db_session, tg):
    c = add_contract(db_session)
    old = add_booking(db_session, c, WED, time(10, 0))

    reqs = await tg.text(CLIENT_BUTTONS["reschedule"]["ru"])  # одна встреча — сразу календарь
    msg = sent(reqs)[0]
    assert "Перенос встречи 25.11.2026 в 10:00" in msg.text
    assert ("26", "cal:day:2026-11-26") in buttons(msg.reply_markup)

    await tg.press("cal:day:2026-11-26")
    reqs = await tg.press("slot:pick:1600")
    assert "Было: 25.11.2026 в 10:00" in edits(reqs)[0].text and "Станет: 26.11.2026 в 16:00" in edits(reqs)[0].text

    reqs = await tg.press("rsc:yes:0")
    assert "Встреча перенесена" in edits(reqs)[0].text
    assert "перенесена клиентом" in texts(reqs, ADMIN)[0] and "Было: 25.11.2026 10:00" in texts(reqs, ADMIN)[0]
    db_session.refresh(old)
    assert old.is_cancelled
    assert db_session.query(Booking).filter_by(is_cancelled=False).one().date == THU


async def test_reschedule_choose_among_several_with_lock(db_session, tg):
    add_booking(db_session, add_contract(db_session, "1-MD"), MON, time(17, 0))  # сегодня — 🔒
    b = add_booking(db_session, add_contract(db_session, "2-MD"), WED, time(10, 0))
    reqs = await tg.text(CLIENT_BUTTONS["reschedule"]["ru"])
    kb = buttons(sent(reqs)[0].reply_markup)
    assert kb[0][0].startswith("🔒") and kb[1] == ("📅 25.11.2026 ⏰ 10:00", f"rsc:pick:{b.id}")
    assert "истёк" in alerts(await tg.press(kb[0][1]))[0].text
    assert "Перенос встречи" in edits(await tg.press(f"rsc:pick:{b.id}"))[0].text


async def test_reschedule_decline_keeps_meeting(db_session, tg):
    b = add_booking(db_session, add_contract(db_session), WED, time(10, 0))
    await tg.text(CLIENT_BUTTONS["reschedule"]["ru"])
    await tg.press("cal:day:2026-11-26")
    await tg.press("slot:pick:1600")
    assert "без изменений" in edits(await tg.press("rsc:no:0"))[0].text
    db_session.refresh(b)
    assert not b.is_cancelled


# ===================== Напоминания =====================

def test_due_reminders(db_session):
    c = add_contract(db_session)
    tomorrow = add_booking(db_session, c, TUE, time(10, 0))
    soon = add_booking(db_session, add_contract(db_session, "2-MD"), MON, time(12, 0))     # через 1 ч
    later = add_booking(db_session, add_contract(db_session, "3-MD"), MON, time(16, 0))    # через 5 ч
    due = {(b.id, kind) for b, kind in due_reminders(db_session, NOW)}
    assert due == {(tomorrow.id, "day"), (soon.id, "hour")}
    assert later.id not in {b for b, _ in due}
    # Ночью напоминание «на завтра» не шлём
    assert not [k for _, k in due_reminders(db_session, tashkent(2026, 11, 23, 2)) if k == "day"]


async def test_send_reminders_marks_sent(db_session):
    add_booking(db_session, add_contract(db_session), TUE, time(10, 0))
    bot = AsyncMock()
    assert await send_reminders(bot) == 1
    assert "Завтра у вас встреча" in bot.send_message.call_args.args[1]
    assert await send_reminders(bot) == 0  # повторно не шлём


# ===================== Персонал: список встреч =====================

async def test_meetings_list_and_admin_cancel(db_session, adm):
    b = add_booking(db_session, add_contract(db_session), TUE, time(10, 0), topic="Отделка")
    await adm.text(ADMIN_BUTTONS["meetings"])
    reqs = await adm.press("mt:period:week")
    msg = sent(reqs)[-1]
    assert "Иванов Иван" in msg.text and "Отделка" in msg.text and "10:00" in msg.text
    cancel_btn = buttons(msg.reply_markup)[0]
    assert cancel_btn[1] == f"mt:cancel:{b.id}"

    await adm.press(cancel_btn[1])
    reqs = await adm.press(f"mt:yes:{b.id}")
    assert "отменена" in edits(reqs)[0].text and "Клиент уведомлён" in edits(reqs)[0].text
    assert "не сможет провести" in texts(reqs, CLIENT)[0]
    db_session.refresh(b)
    assert b.cancelled_by == "admin"


async def test_employee_cannot_cancel(db_session):
    db_session.add(Staff(telegram_id=EMPLOYEE, role="employee"))
    db_session.commit()
    b = add_booking(db_session, add_contract(db_session), TUE, time(10, 0))
    emp = Client(make_dispatcher(), user_id=EMPLOYEE)
    reqs = await emp.press("mt:period:week")
    assert sent(reqs)[-1].reply_markup is None  # без кнопок отмены
    assert "администратор" in alerts(await emp.press(f"mt:yes:{b.id}"))[0].text
    db_session.refresh(b)
    assert not b.is_cancelled


async def test_report_excel(db_session, adm):
    add_booking(db_session, add_contract(db_session), TUE, time(10, 0))
    doc = documents(await adm.text(ADMIN_BUTTONS["report"]))[0]
    df = pd.read_excel(BytesIO(doc.document.data))
    assert df.loc[0, "Статус"] == "Активна" and df.loc[0, "Договор"] == "12345-MD"


# ===================== Расписание CEO =====================

async def test_block_free_slot_and_unblock(db_session, adm):
    await adm.text(ADMIN_BUTTONS["schedule"])
    reqs = await adm.text("24.11.2026")
    assert "10:00 ✅ свободно" in sent(reqs)[0].text
    await adm.press("sch:block:2026-11-24_1000")
    assert db_session.query(BlockedSlot).filter_by(date=TUE, time_slot=time(10, 0)).count() == 1
    await adm.press("sch:unblock:2026-11-24_1000")
    assert db_session.query(BlockedSlot).count() == 0


async def test_block_booked_slot_cancels_and_notifies(db_session, adm):
    b = add_booking(db_session, add_contract(db_session), TUE, time(10, 0))
    reqs = await adm.press("sch:day:2026-11-24")
    assert "10:00 👤 Иванов Иван" in edits(reqs)[0].text
    reqs = await adm.press("sch:blockq:2026-11-24_1000")
    assert "записан клиент" in edits(reqs)[0].text
    reqs = await adm.press("sch:blocky:2026-11-24_1000")
    assert "не сможет провести" in texts(reqs, CLIENT)[0]
    assert "Время CEO закрыто" in texts(reqs, ADMIN)[0]
    db_session.refresh(b)
    assert b.cancelled_by == "block"


async def test_close_and_open_day(db_session, adm, tg):
    add_booking(db_session, add_contract(db_session), WED, time(10, 0))
    await adm.press("sch:closeq:2026-11-25")
    reqs = await adm.press("sch:closey:2026-11-25")
    assert "День закрыт целиком" in edits(reqs)[0].text
    assert db_session.query(Booking).filter_by(is_cancelled=False).count() == 0
    await adm.press("sch:open:2026-11-25")
    assert db_session.query(BlockedSlot).count() == 0


async def test_schedule_bad_date(db_session, adm):
    await adm.text(ADMIN_BUTTONS["schedule"])
    assert "Не понял дату" in texts(await adm.text("завтра"))[0]
    assert "в прошлом" in texts(await adm.text("01.01.2020"))[0]


# ===================== Праздники и договоры (загрузка файлов) =====================

def xlsx(df: pd.DataFrame) -> BytesIO:
    buf = BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    return buf


async def test_holidays_upload_with_conflict(db_session, adm, monkeypatch):
    add_booking(db_session, add_contract(db_session), WED, time(10, 0))
    file = xlsx(pd.DataFrame({"Дата": ["25.11.2026"], "Описание": ["Тест"]}))
    monkeypatch.setattr(admin_handlers, "download_document", AsyncMock(return_value=file))

    await adm.text(ADMIN_BUTTONS["holidays"])
    reqs = await send_document(adm)
    assert "обновлён: 1" in texts(reqs)[0] and "есть встречи (1)" in texts(reqs)[1]
    reqs = await adm.press("adm:hol_cancel:")
    assert "Отменено встреч: 1, клиентов уведомлено: 1" in edits(reqs)[0].text
    assert "нерабочим" in texts(reqs, CLIENT)[0]
    assert db_session.query(Holiday).one().date == WED


async def test_holidays_bad_file(db_session, adm, monkeypatch):
    monkeypatch.setattr(admin_handlers, "download_document",
                        AsyncMock(return_value=xlsx(pd.DataFrame({"Дата": ["вчера"]}))))
    await adm.text(ADMIN_BUTTONS["holidays"])
    assert "Список не изменён" in texts(await send_document(adm))[0]
    assert "Excel" in texts(await send_document(adm, "file.pdf"))[0]


async def test_contracts_upload_and_download(db_session, adm, monkeypatch):
    file = xlsx(pd.DataFrame({
        "Название дома": ["Mahal D", "Джами"], "Номер квартиры": [1, 2], "Подъезд": [1, 1], "Этаж": [2, 3],
        "Номер договора": ["111-MD", "222-GHP"], "ФИО клиента": ["А", "Б"], "Дата сдачи": ["01.12.2026", None],
    }))
    monkeypatch.setattr(admin_handlers, "download_document", AsyncMock(return_value=file))
    await adm.text(ADMIN_BUTTONS["contracts"])
    text = texts(await send_document(adm))[0]
    assert "Добавлено: 2" in text

    await adm.text(ADMIN_BUTTONS["contracts"])
    doc = documents(await adm.press("adm:ctr_dl:"))[0]
    assert sorted(pd.read_excel(BytesIO(doc.document.data))["Номер договора"]) == ["111-MD", "222-GHP"]


# ===================== Договор: поиск, отвязка, перепривязка =====================

async def test_lookup_unbind_rebind(db_session, adm):
    c = add_contract(db_session)
    add_booking(db_session, c, WED, time(10, 0))
    await adm.text(ADMIN_BUTTONS["lookup"])
    reqs = await adm.text(" 12345-md ")
    card = sent(reqs)[0]
    assert "Иванов Иван" in card.text and "25.11.2026 10:00 — активна" in card.text

    await adm.press(f"adm:unbind:{c.id}")
    await adm.press(f"adm:unbind_yes:{c.id}")
    db_session.refresh(c)
    assert c.telegram_id is None

    await adm.press(f"adm:rebind:{c.id}")
    assert "числовой" in texts(await adm.text("abc"))[0]
    await adm.text("555")
    db_session.refresh(c)
    assert c.telegram_id == 555
    assert [entry.action for entry in db_session.query(ContractBindingLog).order_by(ContractBindingLog.id)] == ["unbind", "rebind"]


# ===================== Персонал и настройки =====================

async def test_staff_management(db_session, adm):
    await adm.text(ADMIN_BUTTONS["staff"])
    await adm.press("adm:staff_employee:")
    await adm.text("777")
    assert db_session.query(Staff).filter_by(telegram_id=777, role="employee").count() == 1
    await adm.press("adm:staff_rm:777")
    assert db_session.query(Staff).count() == 0


async def test_cooldown_setting(db_session, adm):
    await adm.text(ADMIN_BUTTONS["settings"])
    await adm.press("adm:cooldown:")
    assert "целое число" in texts(await adm.text("100"))[0]
    assert "Кулдаун: 14" in texts(await adm.text("14"))[0]
    assert get_cooldown_days(db_session) == 14


async def test_menu_button_interrupts_admin_input(db_session, adm):
    await adm.text(ADMIN_BUTTONS["lookup"])
    # Вместо номера договора админ нажал другой раздел — должен открыться раздел
    assert "Настройки" in texts(await adm.text(ADMIN_BUTTONS["settings"]))[0]


# ===================== Регрессия: повтор договора в файле =====================

def test_import_duplicate_contract_in_file(db_session, tmp_path):
    """В Excel один номер договора в двух строках — не падаем, берём последнюю строку."""
    from services.excel import import_contracts
    path = tmp_path / "dup.xlsx"
    pd.DataFrame({
        "Название дома": ["ОзМахал-D 8", "ОзМахал-D 8", "ОзМахал-D 8"],
        "Номер квартиры": [153, 154, 155],
        "Подъезд": [3, 3, 3],
        "Этаж": [9, 9, 9],
        "Номер договора": ["13791-GHP", "13791-ghp ", "13792-GHP"],
        "ФИО клиента": ["Первый", "Второй", "Третий"],
        "Дата сдачи": ["19.11.2026", "19.11.2026", "19.11.2026"],
    }).to_excel(path, index=False)

    r = import_contracts(db_session, str(path))
    assert (r.added, r.updated, r.duplicates) == (2, 0, ["13791-GHP"])
    c = db_session.query(Contract).filter_by(contract_num="13791-GHP").one()
    assert (c.apt_num, c.client_fio) == ("154", "Второй")

    # Повторная загрузка того же файла: договоры уже есть — только обновление
    r = import_contracts(db_session, str(path))
    assert (r.added, r.updated, r.duplicates) == (0, 2, ["13791-GHP"])


async def test_contracts_upload_reports_duplicates(db_session, adm, monkeypatch):
    file = xlsx(pd.DataFrame({
        "Название дома": ["A", "A"], "Номер квартиры": [1, 2], "Подъезд": [1, 1], "Этаж": [1, 1],
        "Номер договора": ["1-GHP", "1-GHP"], "ФИО клиента": ["X", "Y"], "Дата сдачи": [None, None],
    }))
    monkeypatch.setattr(admin_handlers, "download_document", AsyncMock(return_value=file))
    await adm.text(ADMIN_BUTTONS["contracts"])
    text = texts(await send_document(adm))[0]
    assert "Добавлено: 1" in text and "повторяющиеся в файле (1): 1-GHP" in text


async def test_unexpected_error_answers_user(db_session, adm, monkeypatch):
    monkeypatch.setattr(admin_handlers, "download_document", AsyncMock(side_effect=RuntimeError("boom")))
    await adm.text(ADMIN_BUTTONS["contracts"])
    assert "Что-то пошло не так" in texts(await send_document(adm))[0]
