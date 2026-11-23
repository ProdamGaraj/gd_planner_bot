# gd_planner_bot — plan

Telegram bot: company clients (contract holders, any project) book a meeting with the CEO.
Built on the rules of `../dks_bot` (key handover bot).

## Decisions

| Topic | Decision |
|---|---|
| Clients | Same contract holders as dks_bot, all projects (Mahal D restriction removed 2026-11-20) |
| Contract DB | Separate DB, same Excel format as dks_bot. Import skips rows of other houses |
| Slots | Mon–Fri, 30 min. Starts: 10:00, 10:30, 11:00, 11:30, 12:00, 16:00, 16:30, 17:00, 17:30 |
| Capacity | 1 client per slot (enforced by unique index on active `date + time_slot`) |
| Confirmation | Automatic, staff notified like dks_bot |
| Cooldown | 7 days by default, admin setting (`settings.cooldown_days`) |
| Delivery date | Stored, does **not** restrict booking |
| Staff | Same people as dks_bot: same `ADMIN_ID`, `scripts/import_staff_from_dks.py` copies `staff` table |
| CEO schedule | Fixed slot template + holidays + admin blocks (whole day or single slot) |
| Meeting topic | Client writes short topic (optional, "skip" button) — shown to staff |

## Rules inherited from dks_bot

1. Login by contract number (spaces removed, upper-case).
2. Contract bound to first Telegram account that books. Other accounts: "unavailable". Admin unbind/rebind, logged in `contract_binding_log`.
3. One active booking per contract; new booking cancels old one in same commit.
4. Cooldown after last non-cancelled booking (now 7 days, configurable).
5. Earliest date (Tashkent time): Mon–Thu before 12:00 → next working day; after 12:00 → skip one working day; Fri → Monday; Sat/Sun → Tuesday.
6. Weekends + holidays blocked. Holiday import conflicts → admin chooses "cancel & notify" or "keep".
7. Race protection: recheck before insert + unique partial index + `IntegrityError` → "slot just taken".
8. Booking is "past" once slot ends (start + 30 min).
9. Cancel deadline = same rule as #5. Booking on weekend/holiday cancellable until start.
10. Rebook = cancel old + create new.
11. Phone: +998 (12 digits), +7 (11 digits), leading 8 → 7; contact sharing; saved phone reuse.
12. Reminders: day before + 3 h before. Late > 15 min → meeting cancelled (text in every client message).
13. Staff notifications on new / cancelled / rebooked, with profile button and privacy fallback.
14. RU/UZ, auto-detected from `language_code`, toggle button.
15. Roles: super-admin from `.env`, admins/employees in `staff`. Router-level filters.

## Not copied from dks_bot

- Process-wide SSL hacks (env vars, `ssl._create_default_https_context`) — removed. SSL verification is
  switched off only for the bot's Telegram connection (`TELEGRAM_SSL_VERIFY=0`, default, office network
  breaks certificates). Optional `BOT_PROXY`.
- Triplicated booking code — single `services/booking.py`.
- Naive `datetime.now()` / `date.today()` — everything via `now_tashkent()`.
- Unpinned requirements, debug print middleware.
- Services take a `session` argument (testable without monkeypatching globals).

## Structure

```
config.py
main.py
database/   models.py session.py
services/   booking_time.py schedule.py phone.py holidays.py settings.py users.py auth.py
            booking.py excel.py notifier.py          (stages 4–7)
handlers/   common.py client.py admin.py staff.py
keyboards/  reply.py inline.py
locales/    messages.py
scripts/    import_staff_from_dks.py
tests/
```

## Stages

1. [x] Skeleton: config, models, session, `/start` role routing, RU/UZ, Docker.
2. [x] Rule modules + tests: slots, working days, min date, cooldown, cancel deadline, phone, holidays, settings.
3. [x] CEO schedule blocks (`blocked_slots`) + availability service (free slots per day, fully booked days).
4. [x] Client booking flow: contract → binding check → calendar → slot → topic → phone → confirm → staff alert.
   - Language switch mid-flow re-renders current step.
   - Existing future meeting on contract blocks new booking (client must use reschedule/cancel —
     stricter than dks_bot, which silently replaced it and bypassed the cancel deadline).
   - `scripts/import_contracts.py` imports contracts from the command line.
5. [x] My meetings, cancel, rebook.
   - [x] Client cancel (`handlers/client.py`, `services/booking.py`), staff notification.
   - [x] Company-side cancel service + client notification (`cancel_by_company`, `notify_clients_company_cancel`) — admin screens in stage 7.
   - [x] My meetings, reschedule (cancel deadline applies; topic/phone carried over; own meeting excluded from cooldown).
6. [x] Reminders (day before from 10:00, 3 h before) via APScheduler, every 2 min.
7. [x] Admin panel: staff, contracts import (all houses) + export, holidays (+ conflict cancel/keep),
   CEO schedule blocks (slot / whole day, cancels with client notification), cooldown setting, meetings list
   with admin cancel, Excel report, contract lookup, unbind / rebind by Telegram ID (logged).
   Employee panel: meetings list + report.
   - [ ] Contract change review from dks_bot (contract number changed → unbind/cancel/notify per row) — not ported;
     import now only adds/updates rows.
   - [ ] Rebind by @username (dks_bot resolves via bot) — now numeric ID only.
8. [ ] Port dks_bot tests (binding, cancel/rebook, back buttons, auth).
9. [ ] Deploy with test token, smoke test, then production token.
10. [x] Attendance (2026-11-23): at meeting start every admin gets "🕐 Встреча началась — отметьте явку"
    with ✅ Пришёл / ❌ Не пришёл. First mark wins, all admins' messages update, "↩️ Исправить" to change.
    Only today's meetings are prompted (no flood after downtime). Shown in report ("Явка") and contract card.
    `init_db` adds missing columns to the live DB automatically (`add_missing_columns`).
11. [x] No-show ban (2026-11-23): after "Не пришёл" the contract's next meeting is not earlier than
    missed date + N days (setting, default 7, `DEFAULT_NO_SHOW_BAN_DAYS`). Independent of cooldown
    (the later date wins), follows the contract not the account, lifted if the mark is corrected to
    "Пришёл". Client sees why; admin sees ban date on the mark and in the contract card.
12. [x] Auto-confirm (2026-11-23): no attendance mark within 12 h of meeting start → "Пришёл" automatically
    (`attendance_by_name = "автоматически"`, job every 5 min). Admin prompts update; admins can still correct
    via "Исправить" (no-show then triggers the ban). Shown as "(авто)" in card, "автоматически" in report.

## Open items

- CEO office address / phone / coordinates for "Contacts" (defaults copied from dks_bot).
- Uzbek texts need native-speaker check.
