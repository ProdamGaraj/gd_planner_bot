"""Одноразовый перенос персонала (staff) из базы dks_bot.

Использование:
    python -m scripts.import_staff_from_dks ../dks_bot/data/bot_data.db
"""
import sqlite3
import sys
from pathlib import Path

from database.models import Staff
from database.session import SessionLocal, init_db


def main(dks_db_path: str) -> None:
    path = Path(dks_db_path).resolve()
    if not path.is_file():
        raise SystemExit(f"Файл не найден: {path}")

    # Открываем базу dks_bot только на чтение
    src = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        rows = src.execute("SELECT telegram_id, role FROM staff").fetchall()
    finally:
        src.close()

    init_db()
    added = skipped = 0
    with SessionLocal() as session:
        existing = {row[0] for row in session.query(Staff.telegram_id).all()}
        for telegram_id, role in rows:
            if telegram_id is None or telegram_id in existing or role not in ("admin", "employee"):
                skipped += 1
                continue
            session.add(Staff(telegram_id=telegram_id, role=role))
            existing.add(telegram_id)
            added += 1
        session.commit()

    print(f"Добавлено: {added}, пропущено: {skipped}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
