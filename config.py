import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
# Супер-админ (тот же, что в dks_bot)
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
# Необязательный прокси для Telegram API (например, http://proxy:3128)
BOT_PROXY = os.getenv("BOT_PROXY") or None
# Проверка SSL-сертификата Telegram API. По умолчанию выключена: сеть офиса
# ломает сертификаты. Включить: TELEGRAM_SSL_VERIFY=1
TELEGRAM_SSL_VERIFY = os.getenv("TELEGRAM_SSL_VERIFY", "0").strip().lower() in ("1", "true", "yes", "on")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/gd_planner.db")

# Кулдаун между записями по умолчанию (дней); админ может изменить в настройках
DEFAULT_COOLDOWN_DAYS = int(os.getenv("DEFAULT_COOLDOWN_DAYS", "7"))

# Бан за неявку по умолчанию (дней): следующая встреча не раньше даты пропущенной + N
DEFAULT_NO_SHOW_BAN_DAYS = int(os.getenv("DEFAULT_NO_SHOW_BAN_DAYS", "7"))

# На сколько дней вперёд открыта запись
BOOKING_HORIZON_DAYS = int(os.getenv("BOOKING_HORIZON_DAYS", "60"))

# Максимальная длина темы встречи
TOPIC_MAX_LENGTH = 300

# Контакты офиса, где проходит встреча с CEO
OFFICE_CONTACTS = {
    "phone": os.getenv("OFFICE_PHONE", "+998781485115"),
    "address_ru": os.getenv("OFFICE_ADDRESS_RU", "г. Ташкент, улица Истикбол, 39Б"),
    "address_uz": os.getenv("OFFICE_ADDRESS_UZ", "Toshkent sh., Istiqbol ko'chasi, 39B"),
    "working_hours_ru": "Пн-Пт: 10:00-12:30, 16:00-18:00",
    "working_hours_uz": "Dush-Jum: 10:00-12:30, 16:00-18:00",
    "latitude": float(os.getenv("OFFICE_LATITUDE", "41.302006")),
    "longitude": float(os.getenv("OFFICE_LONGITUDE", "69.292259")),
}
