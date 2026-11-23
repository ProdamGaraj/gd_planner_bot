"""Сквозная маршрутизация через настоящий Dispatcher: бот отвечает на каждую кнопку."""
import pytest

from keyboards.reply import ADMIN_BUTTONS, CLIENT_BUTTONS
from tests.harness import Client, alerts, documents, make_dispatcher, sent, texts

ADMIN, EMPLOYEE = 1, 10


@pytest.fixture
def tg(db_session):
    return Client(make_dispatcher())


@pytest.mark.parametrize("key", list(CLIENT_BUTTONS))
@pytest.mark.parametrize("lang", ["ru", "uz"])
async def test_every_client_button_answers(tg, key, lang):
    reqs = await tg.text(CLIENT_BUTTONS[key][lang])
    assert len(sent(reqs)) >= 1
    assert "кнопки меню" not in texts(reqs)[0] and "menyu tugmalaridan" not in texts(reqs)[0]


@pytest.mark.parametrize("key", list(ADMIN_BUTTONS))
async def test_every_admin_button_answers(db_session, key):
    admin = Client(make_dispatcher(), user_id=ADMIN)
    reqs = await admin.text(ADMIN_BUTTONS[key])
    assert sent(reqs) or documents(reqs)
    assert all("кнопки меню" not in t for t in texts(reqs))


async def test_employee_sees_only_meetings_and_report(db_session):
    from database.models import Staff
    db_session.add(Staff(telegram_id=EMPLOYEE, role="employee"))
    db_session.commit()
    emp = Client(make_dispatcher(), user_id=EMPLOYEE)
    assert "За какой период" in texts(await emp.text(ADMIN_BUTTONS["meetings"]))[0]
    assert documents(await emp.text(ADMIN_BUTTONS["report"]))
    # Админские разделы сотруднику недоступны
    assert "кнопки меню" in texts(await emp.text(ADMIN_BUTTONS["staff"]))[0]


async def test_start(tg):
    assert "Здравствуйте" in texts(await tg.text("/start"))[0]


async def test_unknown_text_shows_menu(tg):
    assert "кнопки меню" in texts(await tg.text("привет"))[0]


async def test_admin_buttons_ignored_for_client(tg):
    # Клиент, набравший текст админ-кнопки, получает обычное меню, а не админку
    assert "кнопки меню" in texts(await tg.text(ADMIN_BUTTONS["meetings"]))[0]


async def test_client_cannot_press_admin_callbacks(tg):
    reqs = await tg.press("sch:close:2026-11-24")
    assert "устарела" in alerts(reqs)[0].text


async def test_stale_button_answers(tg):
    reqs = await tg.press("cal:day:2026-11-24")
    assert "устарела" in alerts(reqs)[0].text


async def test_menu_button_interrupts_booking(tg):
    await tg.text(CLIENT_BUTTONS["book"]["ru"])
    # Во время ввода договора клиент нажал «Отменить встречу» — это не номер договора
    assert "нет активных встреч" in texts(await tg.text(CLIENT_BUTTONS["cancel"]["ru"]))[0]
