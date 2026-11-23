from datetime import date, datetime, time

from database.models import AttendancePrompt, Booking, Contract, ContractBindingLog, Staff, UserSettings
from scripts.purge_test_users import collect, purge

TESTER, CLIENT = 777, 100


def test_purge_removes_only_tester_traces(db_session):
    tester_contract = Contract(house_name="A", contract_num="1-GHP", telegram_id=TESTER, username="tester")
    real_contract = Contract(house_name="A", contract_num="2-GHP", telegram_id=CLIENT)
    db_session.add_all([tester_contract, real_contract, Staff(telegram_id=TESTER, role="admin"),
                        UserSettings(telegram_id=TESTER, language="ru", phone="+998"),
                        UserSettings(telegram_id=CLIENT, language="uz")])
    db_session.commit()
    mk = lambda c, uid, t, **kw: Booking(contract_id=c.id, user_telegram_id=uid, date=date(2026, 11, 24),
                                         time_slot=t, client_phone="+998", created_at=datetime(2026, 11, 20), **kw)
    test_b = mk(tester_contract, TESTER, time(10, 0))
    cancelled_test_b = mk(tester_contract, TESTER, time(11, 0), is_cancelled=True)
    real_b = mk(real_contract, CLIENT, time(12, 0))
    db_session.add_all([test_b, cancelled_test_b, real_b])
    db_session.commit()
    db_session.add(AttendancePrompt(booking_id=test_b.id, chat_id=1, message_id=5))
    db_session.commit()

    found = collect(db_session, [TESTER])
    assert {b.id for b in found["bookings"]} == {test_b.id, cancelled_test_b.id}
    purge(db_session, found)

    assert [b.id for b in db_session.query(Booking)] == [real_b.id]
    assert db_session.query(AttendancePrompt).count() == 0
    db_session.refresh(tester_contract)
    assert tester_contract.telegram_id is None                           # настоящий клиент сможет записаться
    assert db_session.query(Contract).count() == 2                       # сами договоры на месте
    assert db_session.get(UserSettings, TESTER) is None
    assert db_session.get(UserSettings, CLIENT) is not None
    assert db_session.query(Staff).filter_by(telegram_id=TESTER).count() == 1  # персонал не трогаем
    log = db_session.query(ContractBindingLog).one()
    assert (log.action, log.old_telegram_id, log.contract_num) == ("unbind", TESTER, "1-GHP")


def test_nothing_found(db_session):
    found = collect(db_session, [123])
    assert not any(found.values())
