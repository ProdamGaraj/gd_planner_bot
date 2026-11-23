from sqlalchemy.orm import Session

from config import ADMIN_ID
from database.models import Staff
from services.auth import ROLE_ADMIN, ROLE_EMPLOYEE

ROLES = (ROLE_ADMIN, ROLE_EMPLOYEE)


def list_staff(session: Session) -> list[Staff]:
    return session.query(Staff).order_by(Staff.role, Staff.telegram_id).all()


def add_staff(session: Session, telegram_id: int, role: str) -> bool:
    """Добавить или сменить роль. False — супер-админ из .env (не трогаем)."""
    if role not in ROLES:
        raise ValueError(f"Неизвестная роль: {role}")
    if telegram_id == ADMIN_ID:
        return False
    staff = session.query(Staff).filter_by(telegram_id=telegram_id).first()
    if staff:
        staff.role = role
    else:
        session.add(Staff(telegram_id=telegram_id, role=role))
    session.commit()
    return True


def remove_staff(session: Session, telegram_id: int) -> bool:
    deleted = session.query(Staff).filter_by(telegram_id=telegram_id).delete()
    session.commit()
    return bool(deleted)
