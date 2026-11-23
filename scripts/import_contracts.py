"""Импорт договоров из Excel (формат dks_bot) из командной строки.

Использование:
    python -m scripts.import_contracts path/to/contracts.xlsx
"""
import sys

from database.session import SessionLocal, init_db
from services.excel import import_contracts


def main(path: str) -> None:
    init_db()
    with SessionLocal() as session:
        r = import_contracts(session, path)
    print(f"Добавлено: {r.added}, обновлено: {r.updated}, без номера: {r.empty}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
