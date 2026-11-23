"""Сквозной прогон на КОПИИ боевой БД: реальные договоры, конкурентные клиенты, действия админа.

Запуск: python -m tests.sim_real_db <копия_боевой_бд.db>
Боевую базу не трогает — передавайте путь к копии.
"""
import asyncio
import logging
import os
import random
import sys
from collections import Counter

DB = sys.argv[1]
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["ADMIN_ID"] = "1"
os.environ["BOT_TOKEN"] = "42:TEST"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import Booking, Contract  # noqa: E402
from database.session import SessionLocal, init_db  # noqa: E402
from keyboards.reply import ADMIN_BUTTONS, CLIENT_BUTTONS  # noqa: E402
from services import booking_time  # noqa: E402
from tests.conftest import tashkent  # noqa: E402
from tests.harness import Client, alerts, buttons, documents, edits, make_dispatcher, sent, texts  # noqa: E402

booking_time.now_tashkent = lambda: tashkent(2026, 11, 23, 11, 0)  # Пн до 12:00
random.seed(7)
errors: list[str] = []
problems: list[str] = []


class ErrorCatcher(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            errors.append(record.getMessage() + (f" | {record.exc_info[1]!r}" if record.exc_info else ""))


def variants(num: str) -> str:
    """Как клиенты реально вводят номер."""
    digits, _, suffix = num.partition("-")
    return random.choice([num, num.lower(), f" {num} ", digits, f"{digits}{suffix.lower()}", f"{digits} {suffix}"])


async def journey(dp, uid: int, contract_num: str, lang: str, outcome: Counter):
    tg = Client(dp, user_id=uid, username=None if uid % 3 == 0 else f"user{uid}", slow=True)
    await tg.text("/start")
    if lang == "uz":
        await tg.text(CLIENT_BUTTONS["language"]["ru"])
    await tg.text(CLIENT_BUTTONS["book"][lang])
    reqs = await tg.text(variants(contract_num))
    cal = [m for m in sent(reqs) if m.reply_markup and "cal:day" in str(m.reply_markup)]
    if not cal:
        problems.append(f"{uid} {contract_num}: no calendar: {[t[:50] for t in texts(reqs)]}")
        return
    days = [cb for _, cb in buttons(cal[0].reply_markup) if cb.startswith("cal:day:")]
    for _ in range(8):
        e = edits(await tg.press(random.choice(days[:5])))
        free = [cb for _, cb in buttons(e[0].reply_markup) if cb.startswith("slot:pick:")] if e else []
        if not free:
            await tg.press("slot:back:")
            continue
        if alerts(await tg.press(random.choice(free))):
            await tg.press("slot:back:")
            continue
        if uid % 2:
            await tg.text("Вопрос по договору и отделке")
        else:
            await tg.press("topic:skip")
        reqs = await (tg.contact("998901234567") if uid % 4 == 0 else tg.text("+998 90 123 45 67"))
        t = texts(reqs, uid)
        if any("Вы записаны" in x or "Siz bosh direktor" in x for x in t):
            outcome["booked"] += 1
            return
        if any("только что заняли" in x or "hozirgina band" in x for x in t):
            continue
        problems.append(f"{uid}: unexpected after phone: {[x[:50] for x in t]}")
        return
    outcome["no free slot"] += 1


async def main():
    logging.getLogger().addHandler(ErrorCatcher())
    init_db()
    with SessionLocal() as s:
        nums = [c.contract_num for c in s.query(Contract).filter(Contract.telegram_id.is_(None)).limit(45).all()]
    print(f"contracts in copy: {len(nums)} used of", end=" ")
    with SessionLocal() as s:
        print(s.query(Contract).count())

    dp = make_dispatcher()
    outcome: Counter = Counter()
    await asyncio.gather(*(journey(dp, 5000 + i, n, "uz" if i % 3 == 0 else "ru", outcome)
                           for i, n in enumerate(nums)))
    print("clients:", dict(outcome))

    # --- повторная попытка записи тем же клиентом: должна упереться в активную встречу ---
    with SessionLocal() as s:
        b = s.query(Booking).filter(Booking.is_cancelled.is_(False)).first()
        uid, num = b.user_telegram_id, b.contract.contract_num
    tg = Client(dp, user_id=uid)
    await tg.text(CLIENT_BUTTONS["book"]["ru"])
    t = texts(await tg.text(num))[0]
    if "уже есть встреча" not in t and "uchrashuv bor" not in t:
        problems.append(f"second booking not blocked: {t[:80]}")
    # --- чужой договор с другого аккаунта ---
    intruder = Client(dp, user_id=999999)
    await intruder.text(CLIENT_BUTTONS["book"]["ru"])
    if "привязан к другому" not in texts(await intruder.text(num))[0]:
        problems.append("foreign contract not rejected")

    # --- перенос и отмена реальными клиентами ---
    with SessionLocal() as s:
        sample = s.query(Booking).filter(Booking.is_cancelled.is_(False)).order_by(Booking.date.desc()).limit(4).all()
        sample = [(b.user_telegram_id, b.id, b.date) for b in sample]
    for uid, bid, d in sample[:2]:
        tg = Client(dp, user_id=uid)
        await tg.text(CLIENT_BUTTONS["cancel"]["ru"])
        await tg.press(f"cxl:pick:{bid}")
        done = edits(await tg.press(f"cxl:yes:{bid}"))[0].text
        if not any(w in done for w in ("отменена", "bekor qilindi")):
            problems.append(f"cancel failed for {bid}")
    for uid, bid, d in sample[2:]:
        tg = Client(dp, user_id=uid)
        reqs = await tg.text(CLIENT_BUTTONS["reschedule"]["ru"])
        days = [cb for m in sent(reqs) if m.reply_markup for _, cb in buttons(m.reply_markup) if cb.startswith("cal:day:")]
        moved = False
        for day in reversed(days):
            e = edits(await tg.press(day))
            free = [cb for _, cb in buttons(e[0].reply_markup) if cb.startswith("slot:pick:")] if e else []
            if free:
                await tg.press(free[0])
                done = edits(await tg.press("rsc:yes:0"))[0].text
                moved = any(w in done for w in ("перенесена", "ko'chirildi"))
                break
            await tg.press("slot:back:")
        if not moved:
            problems.append(f"reschedule failed for {bid}")

    # --- админ ---
    adm = Client(dp, user_id=1)
    for key in ADMIN_BUTTONS:
        reqs = await adm.text(ADMIN_BUTTONS[key])
        if not (sent(reqs) or documents(reqs)):
            problems.append(f"admin button {key} silent")
    reqs = await adm.press("mt:period:all")
    listed = sum(m.text.count("⏰") for m in sent(reqs))
    report = documents(await adm.text(ADMIN_BUTTONS["report"]))
    with SessionLocal() as s:
        active = s.query(Booking).filter(Booking.is_cancelled.is_(False)).all()
        busiest = Counter(b.date for b in active).most_common(1)[0][0]
    if listed != len(active):
        problems.append(f"meetings list shows {listed}, DB has {len(active)} active")
    if not report:
        problems.append("report not sent")
    reqs = await adm.press(f"sch:closeq:{busiest.isoformat()}")
    reqs = await adm.press(f"sch:closey:{busiest.isoformat()}")
    notified = len([m for m in sent(reqs) if m.chat_id not in (1,)])
    with SessionLocal() as s:
        left = s.query(Booking).filter(Booking.is_cancelled.is_(False), Booking.date == busiest).count()
    if left:
        problems.append(f"close day left {left} meetings")
    print(f"closed {busiest}: notified {notified} clients")

    # --- инварианты ---
    with SessionLocal() as s:
        active = s.query(Booking).filter(Booking.is_cancelled.is_(False)).all()
        slots = Counter((b.date, b.time_slot) for b in active)
        per_contract = Counter(b.contract_id for b in active)
        bad_bind = [b.id for b in active if b.contract.telegram_id != b.user_telegram_id]
        weekend = [b.id for b in active if b.date.weekday() >= 5]
    if max(slots.values(), default=0) > 1:
        problems.append("double-booked slot")
    if max(per_contract.values(), default=0) > 1:
        problems.append("contract with 2 active meetings")
    if bad_bind:
        problems.append(f"bookings not owned by contract holder: {bad_bind}")
    if weekend:
        problems.append(f"weekend bookings: {weekend}")

    print(f"active meetings: {len(active)}; logged errors: {len(errors)}; problems: {len(problems)}")
    for x in (errors + problems)[:15]:
        print("  ", x[:300])
    print("RESULT:", "PASS" if not errors and not problems else "FAIL")
    sys.exit(0 if not errors and not problems else 1)


if __name__ == "__main__":
    asyncio.run(main())
