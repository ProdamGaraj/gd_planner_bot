import asyncio
import logging

from aiogram import Bot, Dispatcher

from config import ADMIN_ID, BOT_PROXY, BOT_TOKEN, TELEGRAM_SSL_VERIFY
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database.session import init_db
from handlers import admin, attendance, booking, client, common, errors, fallback, staff
from services.attendance import auto_confirm_attendance, send_attendance_prompts
from services.reminders import send_reminders
from telegram_session import TelegramSession


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан в .env")
    if not ADMIN_ID:
        raise SystemExit("ADMIN_ID не задан в .env — без него никто не получит админ-панель")

    init_db()

    if not TELEGRAM_SSL_VERIFY:
        logging.warning("Проверка SSL-сертификата Telegram API отключена (TELEGRAM_SSL_VERIFY=0)")
    session = TelegramSession(verify_ssl=TELEGRAM_SSL_VERIFY, proxy=BOT_PROXY)
    bot = Bot(token=BOT_TOKEN, session=session)
    dp = Dispatcher()

    # Порядок важен: персонал → админ → общие → клиент → запись → фолбэк (последним)
    dp.include_router(errors.router)
    dp.include_router(attendance.router)
    dp.include_router(staff.router)
    dp.include_router(admin.router)
    dp.include_router(common.router)
    dp.include_router(client.router)
    dp.include_router(booking.router)
    dp.include_router(fallback.router)

    scheduler = AsyncIOScheduler()  # интервальная задача, время считает сама (Ташкент)
    scheduler.add_job(send_reminders, "interval", minutes=2, args=[bot], max_instances=1, coalesce=True)
    # Запрос явки админам — проверка каждую минуту, чтобы прийти к началу встречи
    scheduler.add_job(send_attendance_prompts, "interval", minutes=1, args=[bot], max_instances=1, coalesce=True)
    # Нет отметки явки за 12 ч после начала — считаем, что клиент пришёл
    scheduler.add_job(auto_confirm_attendance, "interval", minutes=5, args=[bot], max_instances=1, coalesce=True)
    scheduler.start()

    logging.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code not in (None, 0):
            raise
