"""Excel-выгрузки для персонала."""
from io import BytesIO

import pandas as pd
from sqlalchemy.orm import Session

from database.models import Booking, Contract

CANCEL_REASONS = {
    "client": "Отменена клиентом",
    "rebook": "Перенесена клиентом",
    "admin": "Отменена администратором",
    "holiday": "Отменена (праздник)",
    "block": "Отменена (CEO занят)",
}


ATTENDANCE = {"came": "Пришёл", "no_show": "Не пришёл"}


def _to_xlsx(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def bookings_report(session: Session) -> bytes:
    rows = []
    query = (
        session.query(Booking, Contract)
        .join(Contract, Booking.contract_id == Contract.id)
        .order_by(Booking.date.desc(), Booking.time_slot.desc())
    )
    for b, c in query:
        status = CANCEL_REASONS.get(b.cancelled_by, "Отменена") if b.is_cancelled else "Активна"
        rows.append({
            "Дата": b.date.strftime("%d.%m.%Y"),
            "Время": b.time_slot.strftime("%H:%M"),
            "Статус": status,
            "Явка": "" if b.is_cancelled else ATTENDANCE.get(b.attendance, "не отмечено"),
            "Явку отметил": b.attendance_by_name or "",
            "ФИО клиента": c.client_fio,
            "Телефон": b.client_phone,
            "Договор": c.contract_num,
            "Кв": c.apt_num,
            "Подъезд": c.entrance,
            "Этаж": c.floor,
            "Тема": b.topic,
            "Telegram": f"@{c.username}" if c.username and c.telegram_id == b.user_telegram_id else b.user_telegram_id,
            "Создана": b.created_at.strftime("%d.%m.%Y %H:%M") if b.created_at else "",
            "Отменена": b.cancelled_at.strftime("%d.%m.%Y %H:%M") if b.cancelled_at else "",
        })
    return _to_xlsx(pd.DataFrame(rows, columns=[
        "Дата", "Время", "Статус", "Явка", "Явку отметил", "ФИО клиента", "Телефон", "Договор", "Кв", "Подъезд", "Этаж",
        "Тема", "Telegram", "Создана", "Отменена",
    ]))


def contracts_export(session: Session) -> bytes:
    """Договоры в формате импорта (можно поправить и загрузить обратно)."""
    contracts = session.query(Contract).order_by(Contract.house_name, Contract.apt_num).all()
    return _to_xlsx(pd.DataFrame(
        [{
            "Название дома": c.house_name,
            "Номер квартиры": c.apt_num,
            "Подъезд": c.entrance,
            "Этаж": c.floor,
            "Номер договора": c.contract_num,
            "ФИО клиента": c.client_fio,
            "Дата сдачи": c.delivery_date.strftime("%d.%m.%Y") if c.delivery_date else "",
        } for c in contracts],
        columns=["Название дома", "Номер квартиры", "Подъезд", "Этаж", "Номер договора", "ФИО клиента", "Дата сдачи"],
    ))
