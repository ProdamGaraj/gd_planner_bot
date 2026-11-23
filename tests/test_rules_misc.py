from datetime import date, datetime, time

import pandas as pd
import pytest
from sqlalchemy.exc import IntegrityError

from database.models import Booking, Contract
from services.booking_time import active_booking_filter, is_booking_past
from services.holidays import get_holiday_dates, import_holidays_from_excel
from services.phone import validate_phone
from services.settings import get_cooldown_days, set_cooldown_days
from services.users import get_user_language, toggle_language
from tests.conftest import tashkent


# ---------- телефон ----------

@pytest.mark.parametrize("raw, expected", [
    ("+998 90 123-45-67", "+998901234567"),
    ("998901234567", "+998901234567"),
    ("+7 (912) 345-67-89", "+79123456789"),
    ("89123456789", "+79123456789"),
])
def test_phone_valid(raw, expected):
    assert validate_phone(raw) == (True, expected)


@pytest.mark.parametrize("raw", ["", "abc", "+99890123456", "+380501234567", "12345"])
def test_phone_invalid(raw):
    assert validate_phone(raw) == (False, "")


# ---------- прошедшая встреча (слот 30 минут) ----------

def test_booking_past_after_slot_end():
    d, t = date(2026, 11, 23), time(10, 0)
    assert not is_booking_past(d, t, tashkent(2026, 11, 23, 10, 29))
    assert is_booking_past(d, t, tashkent(2026, 11, 23, 10, 30))


def _contract(session, num="1-MD"):
    c = Contract(house_name="Mahal D", contract_num=num, client_fio="Test")
    session.add(c)
    session.commit()
    return c


def _booking(contract, d, t, cancelled=False):
    return Booking(
        contract_id=contract.id, date=d, time_slot=t,
        created_at=datetime(2026, 11, 20), is_cancelled=cancelled,
    )


def test_active_booking_filter(db_session):
    c = _contract(db_session)
    d = date(2026, 11, 23)
    db_session.add_all([_booking(c, d, time(10, 0)), _booking(c, d, time(11, 0))])
    db_session.commit()

    active = db_session.query(Booking).filter(active_booking_filter(tashkent(2026, 11, 23, 10, 45))).all()
    assert [b.time_slot for b in active] == [time(11, 0)]


# ---------- один клиент на слот ----------

def test_one_active_booking_per_slot(db_session):
    c1, c2 = _contract(db_session, "1-MD"), _contract(db_session, "2-MD")
    d, t = date(2026, 11, 24), time(10, 0)
    db_session.add(_booking(c1, d, t))
    db_session.commit()

    db_session.add(_booking(c2, d, t))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_cancelled_booking_frees_slot(db_session):
    c1, c2 = _contract(db_session, "1-MD"), _contract(db_session, "2-MD")
    d, t = date(2026, 11, 24), time(10, 0)
    db_session.add(_booking(c1, d, t, cancelled=True))
    db_session.add(_booking(c2, d, t))
    db_session.commit()  # без ошибки


# ---------- настройки ----------

def test_cooldown_setting(db_session):
    assert get_cooldown_days(db_session) == 7
    set_cooldown_days(db_session, 14)
    assert get_cooldown_days(db_session) == 14
    with pytest.raises(ValueError):
        set_cooldown_days(db_session, -1)
    with pytest.raises(ValueError):
        set_cooldown_days(db_session, 91)


# ---------- язык ----------

def test_language_detect_and_toggle(db_session):
    assert get_user_language(db_session, 10, "uz-UZ") == "uz"
    assert get_user_language(db_session, 11, "en") == "ru"
    assert toggle_language(db_session, 10) == "ru"
    assert get_user_language(db_session, 10) == "ru"


# ---------- праздники ----------

def test_import_holidays_replaces_list(db_session, tmp_path):
    first = tmp_path / "h1.xlsx"
    pd.DataFrame({"Дата": ["01.01.2027", "08.03.2027", "01.01.2027"], "Описание": ["НГ", None, "дубль"]}).to_excel(first, index=False)
    assert import_holidays_from_excel(db_session, str(first)) == 2
    assert get_holiday_dates(db_session) == {date(2027, 1, 1), date(2027, 3, 8)}

    second = tmp_path / "h2.xlsx"
    pd.DataFrame({"Дата": ["21.03.2027"]}).to_excel(second, index=False)
    assert import_holidays_from_excel(db_session, str(second)) == 1
    assert get_holiday_dates(db_session) == {date(2027, 3, 21)}


def test_import_holidays_bad_date(db_session, tmp_path):
    path = tmp_path / "bad.xlsx"
    pd.DataFrame({"Дата": ["не дата"]}).to_excel(path, index=False)
    with pytest.raises(ValueError, match="Строка 2"):
        import_holidays_from_excel(db_session, str(path))
