from aiogram import types
from aiogram.filters import BaseFilter

from config import ADMIN_ID
from database.models import Staff
from database.session import SessionLocal

ROLE_ADMIN = "admin"
ROLE_EMPLOYEE = "employee"


def get_role(user_id: int) -> str | None:
    """'admin' | 'employee' | None (клиент)."""
    if user_id == ADMIN_ID:
        return ROLE_ADMIN
    with SessionLocal() as session:
        staff = session.query(Staff).filter_by(telegram_id=user_id).first()
        return staff.role if staff else None


def is_admin(user_id: int) -> bool:
    return get_role(user_id) == ROLE_ADMIN


def is_staff(user_id: int) -> bool:
    return get_role(user_id) is not None


def staff_recipients() -> list[int]:
    """Все, кто получает уведомления о записях: персонал + супер-админ."""
    with SessionLocal() as session:
        ids = [row[0] for row in session.query(Staff.telegram_id).all()]
    if ADMIN_ID and ADMIN_ID not in ids:
        ids.append(ADMIN_ID)
    return ids


class IsAdminFilter(BaseFilter):
    async def __call__(self, event: types.Message | types.CallbackQuery) -> bool:
        return is_admin(event.from_user.id)


class IsStaffFilter(BaseFilter):
    async def __call__(self, event: types.Message | types.CallbackQuery) -> bool:
        return is_staff(event.from_user.id)
