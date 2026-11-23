"""Удаление следов тестовых пользователей: встречи, привязки договоров, настройки.

Без --apply только показывает, что будет удалено. С --apply сначала делает
резервную копию базы (data/backup-ГГГГММДД-ЧЧММСС.db), потом удаляет.

    python -m scripts.purge_test_users 748689055 1902812215            # посмотреть
    python -m scripts.purge_test_users 748689055 1902812215 --apply    # удалить

В Docker:
    docker compose exec gd_planner_bot python -m scripts.purge_test_users <id> ... [--apply]

Что делает для указанных Telegram ID:
  - удаляет их встречи (созданные ими или по договорам, привязанным к ним) и запросы явки по ним;
  - отвязывает договоры, привязанные к ним (иначе настоящий клиент не сможет записаться),
    с записью в журнал привязок;
  - удаляет их язык/телефон (user_settings).
Персонал (staff) и сами договоры не трогает.
"""
import argparse
import os
import sqlite3
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session

from config import DATABASE_URL
from database.models import AttendancePrompt, Booking, Contract, ContractBindingLog, UserSettings
from database.session import SessionLocal, init_db

PURGE_ADMIN_ID = 0  # в журнале привязок: действие выполнено скриптом, а не админом в боте


def collect(session: Session, ids: list[int]) -> dict:
    bound = session.query(Contract).filter(Contract.telegram_id.in_(ids)).all()
    bookings = (
        session.query(Booking)
        .join(Contract, Booking.contract_id == Contract.id)
        .filter(or_(Booking.user_telegram_id.in_(ids), Contract.telegram_id.in_(ids)))
        .order_by(Booking.date, Booking.time_slot)
        .all()
    )
    settings = session.query(UserSettings).filter(UserSettings.telegram_id.in_(ids)).all()
    return {"bookings": bookings, "contracts": bound, "settings": settings}


def describe(found: dict) -> str:
    lines = [f"Встреч к удалению: {len(found['bookings'])}"]
    for b in found["bookings"]:
        status = "отменена" if b.is_cancelled else "активна"
        lines.append(f"  #{b.id} {b.date:%d.%m.%Y} {b.time_slot:%H:%M} дог. {b.contract.contract_num} "
                     f"(создал {b.user_telegram_id}, {status})")
    lines.append(f"Договоров к отвязке: {len(found['contracts'])}")
    for c in found["contracts"]:
        lines.append(f"  {c.contract_num} ← Telegram {c.telegram_id}" + (f" @{c.username}" if c.username else ""))
    lines.append(f"Настроек пользователей к удалению: {len(found['settings'])}")
    return "\n".join(lines)


def purge(session: Session, found: dict) -> None:
    booking_ids = [b.id for b in found["bookings"]]
    if booking_ids:
        session.query(AttendancePrompt).filter(AttendancePrompt.booking_id.in_(booking_ids)).delete(
            synchronize_session=False)
        session.query(Booking).filter(Booking.id.in_(booking_ids)).delete(synchronize_session=False)
    now = datetime.now()
    for c in found["contracts"]:
        session.add(ContractBindingLog(
            contract_id=c.id, contract_num=c.contract_num, action="unbind",
            old_telegram_id=c.telegram_id, old_username=c.username, new_telegram_id=None, new_username=None,
            admin_telegram_id=PURGE_ADMIN_ID, admin_username=None, created_at=now,
            note="purge_test_users: удаление тестового пользователя",
        ))
        c.telegram_id = None
        c.username = None
        c.href = None
    for s in found["settings"]:
        session.delete(s)
    session.commit()


def backup_database() -> str:
    path = make_url(DATABASE_URL).database
    target = os.path.join(os.path.dirname(os.path.abspath(path)), f"backup-{datetime.now():%Y%m%d-%H%M%S}.db")
    src, dst = sqlite3.connect(path), sqlite3.connect(target)
    try:
        src.backup(dst)  # согласованная копия даже при работающем боте
    finally:
        dst.close()
        src.close()
    return target


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("telegram_ids", nargs="+", type=int, help="Telegram ID тестовых пользователей")
    parser.add_argument("--apply", action="store_true", help="действительно удалить (иначе только показать)")
    args = parser.parse_args(argv)

    init_db()
    with SessionLocal() as session:
        found = collect(session, args.telegram_ids)
        print(describe(found))
        if not any(found.values()):
            print("\nНечего удалять.")
            return
        if not args.apply:
            print("\nЭто предпросмотр. Чтобы удалить, добавьте --apply")
            return
        print(f"\nРезервная копия: {backup_database()}")
        purge(session, found)
        print("Готово.")


if __name__ == "__main__":
    main()
