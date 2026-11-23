from aiogram.fsm.state import State, StatesGroup


class BookingSteps(StatesGroup):
    entering_contract = State()
    selecting_date = State()
    selecting_time = State()
    entering_topic = State()
    entering_phone = State()
    confirming_reschedule = State()  # только в режиме переноса


class AdminSteps(StatesGroup):
    schedule_date = State()
    holidays_file = State()
    holidays_conflicts = State()
    contracts_file = State()
    lookup_contract = State()
    rebind_target = State()
    staff_add_id = State()
    cooldown_value = State()
    no_show_ban_value = State()
