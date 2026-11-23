from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, String, Time, text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Contract(Base):
    __tablename__ = "contracts"
    id = Column(Integer, primary_key=True)
    house_name = Column(String, nullable=False)
    apt_num = Column(String)
    entrance = Column(String)
    floor = Column(Integer)
    contract_num = Column(String, unique=True, index=True, nullable=False)
    client_fio = Column(String)
    # Хранится для справки, на запись к CEO не влияет
    delivery_date = Column(Date, nullable=True)
    # Telegram-аккаунт, к которому привязан договор (первый, кто записался)
    telegram_id = Column(Integer, nullable=True, index=True)
    username = Column(String, nullable=True)
    href = Column(String, nullable=True)

    bookings = relationship("Booking", back_populates="contract")


class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False, index=True)
    user_telegram_id = Column(Integer, nullable=True, index=True)  # кто создал запись
    date = Column(Date, nullable=False, index=True)
    time_slot = Column(Time, nullable=False)
    client_phone = Column(String)
    topic = Column(String, nullable=True)  # тема встречи
    created_at = Column(DateTime, nullable=False)
    reminder_day_sent = Column(Boolean, default=False, nullable=False)
    reminder_hour_sent = Column(Boolean, default=False, nullable=False)
    is_cancelled = Column(Boolean, default=False, nullable=False)
    # 'client' | 'rebook' | 'admin' | 'holiday' | 'block'
    cancelled_by = Column(String, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)  # время по Ташкенту, без tzinfo

    # Явка: None — не отмечено, 'came' | 'no_show'. Отмечает любой админ после начала встречи.
    attendance = Column(String, nullable=True)
    attendance_by = Column(Integer, nullable=True)
    attendance_by_name = Column(String, nullable=True)
    attendance_at = Column(DateTime, nullable=True)
    attendance_prompted = Column(Boolean, default=False, nullable=False)  # админам ушёл запрос

    contract = relationship("Contract", back_populates="bookings")

    __table_args__ = (
        # CEO принимает одного клиента на слот: не может быть двух активных
        # записей на одну дату и время (защита от гонки).
        Index(
            "ux_bookings_active_slot", "date", "time_slot",
            unique=True,
            sqlite_where=text("is_cancelled = 0"),
            postgresql_where=text("is_cancelled = false"),
        ),
    )


class AttendancePrompt(Base):
    """Сообщение «отметьте явку», отправленное админу — чтобы обновить у всех после отметки."""
    __tablename__ = "attendance_prompts"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False, index=True)
    chat_id = Column(Integer, nullable=False)
    message_id = Column(Integer, nullable=False)


class BlockedSlot(Base):
    """Закрытое админом время CEO. time_slot = NULL — закрыт весь день."""
    __tablename__ = "blocked_slots"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    time_slot = Column(Time, nullable=True)
    reason = Column(String, nullable=True)
    created_by = Column(Integer, nullable=True)


class Holiday(Base):
    __tablename__ = "holidays"
    id = Column(Integer, primary_key=True)
    date = Column(Date, unique=True, nullable=False, index=True)
    description = Column(String, nullable=True)


class UserSettings(Base):
    """Язык и сохранённый телефон пользователя."""
    __tablename__ = "user_settings"
    telegram_id = Column(Integer, primary_key=True, autoincrement=False)
    language = Column(String, default="ru", nullable=False)
    phone = Column(String, nullable=True)


class Staff(Base):
    __tablename__ = "staff"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    role = Column(String, nullable=False)  # 'admin' | 'employee'


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)


class ContractBindingLog(Base):
    """Журнал изменений привязки договора к Telegram-аккаунту."""
    __tablename__ = "contract_binding_log"
    id = Column(Integer, primary_key=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), index=True, nullable=False)
    contract_num = Column(String, index=True, nullable=True)
    action = Column(String, nullable=False)  # 'bind' | 'unbind' | 'rebind'
    old_telegram_id = Column(Integer, nullable=True)
    old_username = Column(String, nullable=True)
    new_telegram_id = Column(Integer, nullable=True)
    new_username = Column(String, nullable=True)
    admin_telegram_id = Column(Integer, index=True, nullable=False)
    admin_username = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)
    note = Column(String, nullable=True)
