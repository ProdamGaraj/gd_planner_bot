"""Договоры для админа: поиск, отвязка/перепривязка Telegram-аккаунта (с журналом)."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import Booking, Contract, ContractBindingLog
from services import booking_time
from services.users import build_tg_href


def contract_stats(session: Session) -> tuple[int, int]:
    """(всего договоров, привязанных к Telegram)."""
    base = session.query(func.count(Contract.id))
    return base.scalar(), base.filter(Contract.telegram_id.is_not(None)).scalar()


def contract_history(session: Session, contract_id: int, limit: int = 10) -> list[Booking]:
    return (
        session.query(Booking)
        .filter(Booking.contract_id == contract_id)
        .order_by(Booking.date.desc(), Booking.time_slot.desc())
        .limit(limit)
        .all()
    )


def _log(session, contract, action, old_id, old_username, new_id, new_username, admin_id, admin_username, note=None):
    session.add(ContractBindingLog(
        contract_id=contract.id,
        contract_num=contract.contract_num,
        action=action,
        old_telegram_id=old_id,
        old_username=old_username,
        new_telegram_id=new_id,
        new_username=new_username,
        admin_telegram_id=admin_id,
        admin_username=admin_username,
        created_at=booking_time.now_tashkent().replace(tzinfo=None),
        note=note,
    ))


def unbind_contract(session: Session, contract: Contract, admin_id: int, admin_username: str | None) -> None:
    """Отвязать договор: следующий, кто запишется по нему, станет владельцем."""
    _log(session, contract, "unbind", contract.telegram_id, contract.username, None, None, admin_id, admin_username)
    contract.telegram_id = None
    contract.username = None
    contract.href = None
    session.commit()


def rebind_contract(
    session: Session, contract: Contract, new_telegram_id: int, admin_id: int, admin_username: str | None,
) -> None:
    """Привязать договор к другому аккаунту (по Telegram ID)."""
    _log(session, contract, "rebind", contract.telegram_id, contract.username, new_telegram_id, None,
         admin_id, admin_username)
    contract.telegram_id = new_telegram_id
    contract.username = None  # обновится при следующей записи клиента
    contract.href = build_tg_href(new_telegram_id, None)
    session.commit()


def binding_log(session: Session, contract_id: int, limit: int = 5) -> list[ContractBindingLog]:
    return (
        session.query(ContractBindingLog)
        .filter(ContractBindingLog.contract_id == contract_id)
        .order_by(ContractBindingLog.created_at.desc())
        .limit(limit)
        .all()
    )

