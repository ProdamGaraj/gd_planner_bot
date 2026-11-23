"""Праздничные/нерабочие дни: выборка, импорт и экспорт Excel."""
import logging
from datetime import date, datetime, timedelta
from io import BytesIO

import pandas as pd
from sqlalchemy.orm import Session

from database.models import Holiday

EXPECTED_COLUMNS = ["Дата", "Описание"]
# Горизонт, на который подгружаются праздники для расчёта правил
RULES_HORIZON_DAYS = 60


def get_all_holidays(session: Session) -> list[Holiday]:
    return session.query(Holiday).order_by(Holiday.date).all()


def get_holiday_dates(session: Session, start: date | None = None, end: date | None = None) -> set[date]:
    query = session.query(Holiday.date)
    if start:
        query = query.filter(Holiday.date >= start)
    if end:
        query = query.filter(Holiday.date <= end)
    return {row[0] for row in query.all()}


def upcoming_holiday_dates(session: Session, start: date, days: int = RULES_HORIZON_DAYS) -> set[date]:
    return get_holiday_dates(session, start, start + timedelta(days=days))


def export_holidays_excel(session: Session) -> bytes:
    """Текущий список праздников — он же шаблон для загрузки."""
    holidays = get_all_holidays(session)
    df = pd.DataFrame(
        {
            "Дата": [h.date.strftime("%d.%m.%Y") for h in holidays],
            "Описание": [h.description or "" for h in holidays],
        },
        columns=EXPECTED_COLUMNS,
    )
    buf = BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def import_holidays_from_excel(session: Session, file_path: str) -> int:
    """Полностью заменяет список праздников данными из Excel.

    Столбцы: «Дата» (ДД.ММ.ГГГГ), «Описание» (необязательно).
    Без заголовков — первый столбец считается датой, второй описанием.
    """
    df = pd.read_excel(file_path)
    df.columns = [str(c).strip() for c in df.columns]
    if len(df.columns) == 0:
        raise ValueError("Файл не содержит столбцов. Ожидается минимум столбец «Дата».")

    date_col = "Дата" if "Дата" in df.columns else df.columns[0]
    if "Описание" in df.columns:
        desc_col = "Описание"
    elif len(df.columns) >= 2:
        desc_col = df.columns[1]
    else:
        desc_col = None

    parsed: dict[date, str] = {}
    for idx, row in df.iterrows():
        raw = row[date_col]
        if pd.isna(raw):
            continue
        day = _parse_date(raw)
        if day is None:
            raise ValueError(
                f"Строка {idx + 2}: не удалось распознать дату «{raw}». Ожидается формат ДД.ММ.ГГГГ"
            )
        if day in parsed:
            continue
        desc = ""
        if desc_col is not None and not pd.isna(row[desc_col]):
            desc = str(row[desc_col]).strip()
        parsed[day] = desc

    session.query(Holiday).delete()
    for day, desc in parsed.items():
        session.add(Holiday(date=day, description=desc or None))
    session.commit()

    logging.info("Импортировано %d праздничных дней.", len(parsed))
    return len(parsed)


def _parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return pd.to_datetime(s, dayfirst=True).date()
    except (ValueError, TypeError):
        return None
