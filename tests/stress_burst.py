"""Нагрузочный прогон: N клиентов одновременно проходят запись через настоящий Dispatcher.

Файловая SQLite (как в проде), медленная «сеть» Telegram, обработка апдейтов задачами
(как start_polling). Проверяет: нет ошибок, нет двойных записей, каждый слот — один клиент.

Запуск: python -m tests.stress_burst <clients> <db_path>
"""
import asyncio
import logging
import os
import random
import sys
import time as clock
from datetime import date

N = int(sys.argv[1]) if len(sys.argv) > 1 else 60
DB = sys.argv[2] if len(sys.argv) > 2 else "stress.db"
if os.path.exists(DB):
    os.remove(DB)
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["ADMIN_ID"] = "1"
os.environ["BOT_TOKEN"] = "42:TEST"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram.methods import AnswerCallbackQuery, SendMessage  # noqa: E402

from database.models import Booking, Contract  # noqa: E402
from database.session import SessionLocal, init_db  # noqa: E402
from keyboards.reply import CLIENT_BUTTONS  # noqa: E402
from services import booking_time  # noqa: E402
from tests.conftest import tashkent  # noqa: E402
from tests.harness import CaptureSession, Client, buttons, edits, make_dispatcher, sent  # noqa: E402

NOW = tashkent(2026, 11, 23, 11, 0)
booking_time.now_tashkent = lambda: NOW

errors: list[str] = []


class SlowSession(CaptureSession):
    """Каждый запрос к Telegram «идёт» 50–300 мс."""

    async def make_request(self, bot, method, timeout=None):
        await asyncio.sleep(random.uniform(0.05, 0.3))
        return await super().make_request(bot, method, timeout)


class ErrorCatcher(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            errors.append(record.getMessage() + (f" | {record.exc_info[1]!r}" if record.exc_info else ""))


async def client_journey(dp, i: int, results: dict):
    tg = Client(dp, user_id=1000 + i, username=f"u{i}")
    tg.bot.session = SlowSession()
    await tg.text(CLIENT_BUTTONS["book"]["ru"])
    reqs = await tg.text(f"{20000 + i}-GHP")
    cal = [m for m in sent(reqs) if m.reply_markup and "cal:" in str(m.reply_markup)]
    if not cal:
        results[i] = "no calendar: " + " | ".join(m.text[:60] for m in sent(reqs))
        return
    days = [cb for _, cb in buttons(cal[0].reply_markup) if cb.startswith("cal:day:")]
    for attempt in range(6):  # клиенты конкурируют за слоты — пробуем несколько раз
        reqs = await tg.press(random.choice(days[:3]))  # все давятся в первые дни
        e = edits(reqs)
        if not e or not e[0].reply_markup:
            continue
        free = [cb for _, cb in buttons(e[0].reply_markup) if cb.startswith("slot:pick:")]
        if not free:
            await tg.press("slot:back:")
            continue
        reqs = await tg.press(random.choice(free))
        if any(isinstance(r, AnswerCallbackQuery) and r.show_alert for r in reqs):
            await tg.press("slot:back:")  # слот увели — назад к календарю
            continue
        await tg.press("topic:skip")
        reqs = await tg.text("+998901234567")
        texts = [m.text for m in sent(reqs, tg.user.id)]
        if any("Вы записаны" in t for t in texts):
            results[i] = "booked"
            return
        if any("только что заняли" in t for t in texts):
            continue  # бот вернул к выбору времени
        results[i] = "unexpected: " + " | ".join(t[:60] for t in texts)
        return
    results[i] = "gave up (all slots taken)"


async def main():
    logging.getLogger().addHandler(ErrorCatcher())
    init_db()
    with SessionLocal() as s:
        s.add_all(Contract(house_name="ОзМахал-D 8", contract_num=f"{20000 + i}-GHP", client_fio=f"Client {i}",
                           apt_num=str(i)) for i in range(N))
        s.commit()

    dp = make_dispatcher()
    results: dict[int, str] = {}
    t0 = clock.monotonic()
    await asyncio.gather(*(client_journey(dp, i, results) for i in range(N)))
    elapsed = clock.monotonic() - t0
    await asyncio.sleep(0.5)

    with SessionLocal() as s:
        active = s.query(Booking).filter(Booking.is_cancelled.is_(False)).all()
        per_slot: dict[tuple[date, object], int] = {}
        per_contract: dict[int, int] = {}
        for b in active:
            per_slot[(b.date, b.time_slot)] = per_slot.get((b.date, b.time_slot), 0) + 1
            per_contract[b.contract_id] = per_contract.get(b.contract_id, 0) + 1

    summary: dict[str, int] = {}
    for r in results.values():
        key = r if r in ("booked", "gave up (all slots taken)") else "OTHER"
        summary[key] = summary.get(key, 0) + 1
    print(f"clients={N} time={elapsed:.1f}s results={summary}")
    print(f"bookings={len(active)} max_per_slot={max(per_slot.values(), default=0)} "
          f"max_per_contract={max(per_contract.values(), default=0)}")
    for i, r in results.items():
        if r not in ("booked", "gave up (all slots taken)"):
            print(f"  client {i}: {r}")
    print(f"logged errors: {len(errors)}")
    for e in errors[:5]:
        print("  ", e[:300])

    ok = (not errors and max(per_slot.values(), default=0) <= 1 and max(per_contract.values(), default=0) <= 1
          and summary.get("booked", 0) == len(active) and "OTHER" not in summary)
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
