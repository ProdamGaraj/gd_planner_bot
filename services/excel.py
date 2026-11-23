"""Импорт договоров из Excel (формат dks_bot)."""
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd
from sqlalchemy.orm import Session

from database.models import Contract
from services.booking import normalize_contract_num

EXPECTED_COLUMNS = [
    "Название дома",
    "Номер квартиры",
    "Подъезд",
    "Этаж",
    "Номер договора",
    "ФИО клиента",
    "Дата сдачи",
]


@dataclass
class ImportResult:
    added: int = 0
    updated: int = 0
    empty: int = 0           # строки без номера договора
    duplicates: list[str] = field(default_factory=list)  # номера, встретившиеся в файле несколько раз
    warnings: list[str] = field(default_factory=list)    # пропущенные кривые ячейки


def _clean_str(value) -> str | None:
    """Excel превращает 12 в 12.0 — возвращаем '12'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
    except (ValueError, OverflowError):
        pass
    return s


def _parse_date(value) -> date | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Не удалось распознать дату сдачи «{s}», ожидается ДД.ММ.ГГГГ")


def _column_map(df: pd.DataFrame) -> dict[str, str]:
    """По заголовкам, если все на месте, иначе — по позиции (как в dks_bot)."""
    df.columns = [str(c).strip() for c in df.columns]
    if all(c in df.columns for c in EXPECTED_COLUMNS):
        return {c: c for c in EXPECTED_COLUMNS}
    if len(df.columns) < len(EXPECTED_COLUMNS):
        raise ValueError(
            f"В файле {len(df.columns)} столбцов, ожидается {len(EXPECTED_COLUMNS)}: "
            + ", ".join(EXPECTED_COLUMNS)
        )
    return {expected: df.columns[i] for i, expected in enumerate(EXPECTED_COLUMNS)}


def import_contracts(session: Session, file_path) -> ImportResult:
    """Добавляет новые договоры и обновляет данные существующих (все дома из файла).

    Привязку к Telegram и записи не трогает.
    """
    df = pd.read_excel(file_path)
    cols = _column_map(df)
    result = ImportResult()
    # Все договоры БД + добавленные из этого файла: повтор номера в файле
    # обновляет уже найденный договор, а не создаёт второй (unique contract_num)
    known: dict[str, Contract] = {c.contract_num: c for c in session.query(Contract).all()}
    seen: set[str] = set()
    duplicates: dict[str, None] = {}  # упорядоченное множество

    for idx, row in df.iterrows():
        house = _clean_str(row[cols["Название дома"]]) or ""

        # _clean_str: номер без суффикса Excel хранит числом — 12345.0 → «12345»
        num = normalize_contract_num(_clean_str(row[cols["Номер договора"]]) or "")
        if not num:
            result.empty += 1
            continue

        # Этаж и дата сдачи справочные: кривая ячейка не должна срывать загрузку всего файла
        line = idx + 2
        floor_raw = _clean_str(row[cols["Этаж"]])
        try:
            floor = int(floor_raw) if floor_raw else None
        except ValueError:
            floor = None
            result.warnings.append(f"строка {line}: этаж «{floor_raw}» не число — пропущен")
        try:
            delivery = _parse_date(row[cols["Дата сдачи"]])
        except ValueError:
            delivery = None
            result.warnings.append(f"строка {line}: дата сдачи «{row[cols['Дата сдачи']]}» не распознана — пропущена")

        data = {
            "house_name": house,
            "apt_num": _clean_str(row[cols["Номер квартиры"]]),
            "entrance": _clean_str(row[cols["Подъезд"]]),
            "floor": floor,
            "client_fio": _clean_str(row[cols["ФИО клиента"]]),
            "delivery_date": delivery,
        }
        if num in seen:
            duplicates[num] = None  # последняя строка с этим номером побеждает
        contract = known.get(num)
        if contract:
            for key, value in data.items():
                setattr(contract, key, value)
            if num not in seen:
                result.updated += 1
        else:
            contract = Contract(contract_num=num, **data)
            session.add(contract)
            known[num] = contract
            result.added += 1
        seen.add(num)

    session.commit()
    result.duplicates = list(duplicates)
    return result
