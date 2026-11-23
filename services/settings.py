from sqlalchemy.orm import Session

from config import DEFAULT_COOLDOWN_DAYS, DEFAULT_NO_SHOW_BAN_DAYS
from database.models import Setting

COOLDOWN_KEY = "cooldown_days"
MAX_COOLDOWN_DAYS = 90


def get_setting(session: Session, key: str) -> str | None:
    row = session.get(Setting, key)
    return row.value if row else None


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))
    session.commit()


def get_cooldown_days(session: Session) -> int:
    raw = get_setting(session, COOLDOWN_KEY)
    try:
        return int(raw) if raw is not None else DEFAULT_COOLDOWN_DAYS
    except ValueError:
        return DEFAULT_COOLDOWN_DAYS


def set_cooldown_days(session: Session, days: int) -> None:
    if not 0 <= days <= MAX_COOLDOWN_DAYS:
        raise ValueError(f"Кулдаун должен быть от 0 до {MAX_COOLDOWN_DAYS} дней")
    set_setting(session, COOLDOWN_KEY, str(days))


NO_SHOW_BAN_KEY = "no_show_ban_days"
MAX_NO_SHOW_BAN_DAYS = 90


def get_no_show_ban_days(session: Session) -> int:
    """Сколько дней после неявки клиент не может записаться (0 — без бана)."""
    raw = get_setting(session, NO_SHOW_BAN_KEY)
    try:
        return int(raw) if raw is not None else DEFAULT_NO_SHOW_BAN_DAYS
    except ValueError:
        return DEFAULT_NO_SHOW_BAN_DAYS


def set_no_show_ban_days(session: Session, days: int) -> None:
    if not 0 <= days <= MAX_NO_SHOW_BAN_DAYS:
        raise ValueError(f"Бан за неявку должен быть от 0 до {MAX_NO_SHOW_BAN_DAYS} дней")
    set_setting(session, NO_SHOW_BAN_KEY, str(days))
