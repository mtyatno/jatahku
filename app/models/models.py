import uuid
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import (
    String, Text, Numeric, Boolean, Integer, Date, DateTime,
    ForeignKey, Enum as SAEnum, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
import enum


# --- Enums ---

class HouseholdRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class TransactionSource(str, enum.Enum):
    telegram = "telegram"
    webapp = "webapp"


class RecurringFrequency(str, enum.Enum):
    weekly = "weekly"
    monthly = "monthly"
    yearly = "yearly"


# --- Mixins ---

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# --- Models ---

class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    telegram_id: Mapped[str | None] = mapped_column(
        String(50), unique=True, index=True
    )
    password_hash: Mapped[str | None] = mapped_column(String(255))
    timezone: Mapped[str | None] = mapped_column(String(30), default="Asia/Jakarta")
    profile_pic: Mapped[str | None] = mapped_column(String(500), nullable=True)
    default_cooling_threshold: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    default_daily_limit: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    default_is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    plan: Mapped[str | None] = mapped_column(String(10), default="basic")
    last_login: Mapped[datetime | None] = mapped_column(nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    household_memberships: Mapped[list["HouseholdMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user")
    incomes: Mapped[list["Income"]] = relationship(back_populates="user")


class Household(TimestampMixin, Base):
    __tablename__ = "households"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(10), default="IDR")
    invite_code: Mapped[str | None] = mapped_column(String(20), unique=True)

    # Relationships
    members: Mapped[list["HouseholdMember"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    envelope_groups: Mapped[list["EnvelopeGroup"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    envelopes: Mapped[list["Envelope"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    incomes: Mapped[list["Income"]] = relationship(back_populates="household")


class HouseholdMember(TimestampMixin, Base):
    __tablename__ = "household_members"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"))
    role: Mapped[HouseholdRole] = mapped_column(
        SAEnum(HouseholdRole), default=HouseholdRole.member
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="household_memberships")
    household: Mapped["Household"] = relationship(back_populates="members")


class EnvelopeGroup(TimestampMixin, Base):
    __tablename__ = "envelope_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"))
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    household: Mapped["Household"] = relationship(back_populates="envelope_groups")
    envelopes: Mapped[list["Envelope"]] = relationship(back_populates="group")


class Envelope(TimestampMixin, Base):
    __tablename__ = "envelopes"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"))
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("envelope_groups.id")
    )
    name: Mapped[str] = mapped_column(String(100))
    emoji: Mapped[str] = mapped_column(String(10), default="")
    budget_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0")
    )
    is_rollover: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, default=None
    )
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_limit: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    cooling_threshold: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)

    # Relationships
    household: Mapped["Household"] = relationship(back_populates="envelopes")
    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_id])
    group: Mapped["EnvelopeGroup | None"] = relationship(back_populates="envelopes")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="envelope")
    allocations: Mapped[list["Allocation"]] = relationship(back_populates="envelope")
    goals: Mapped[list["Goal"]] = relationship(back_populates="envelope")
    recurring_txns: Mapped[list["RecurringTransaction"]] = relationship(
        back_populates="envelope"
    )
    monthly_snapshots: Mapped[list["MonthlySnapshot"]] = relationship(
        back_populates="envelope"
    )


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    envelope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("envelopes.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    description: Mapped[str] = mapped_column(String(500))
    source: Mapped[TransactionSource] = mapped_column(
        SAEnum(TransactionSource), default=TransactionSource.webapp
    )
    transaction_date: Mapped[date] = mapped_column(Date, default=date.today)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    envelope: Mapped["Envelope"] = relationship(back_populates="transactions")
    user: Mapped["User"] = relationship(back_populates="transactions")


class Income(TimestampMixin, Base):
    __tablename__ = "incomes"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    description: Mapped[str] = mapped_column(String(500))
    income_date: Mapped[date] = mapped_column(Date, default=date.today)

    # Relationships
    household: Mapped["Household"] = relationship(back_populates="incomes")
    user: Mapped["User"] = relationship(back_populates="incomes")
    allocations: Mapped[list["Allocation"]] = relationship(back_populates="income")


class Allocation(TimestampMixin, Base):
    __tablename__ = "allocations"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    income_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incomes.id"))
    envelope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("envelopes.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))

    # Relationships
    income: Mapped["Income"] = relationship(back_populates="allocations")
    envelope: Mapped["Envelope"] = relationship(back_populates="allocations")


class RecurringTransaction(TimestampMixin, Base):
    __tablename__ = "recurring_txns"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    envelope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("envelopes.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    description: Mapped[str] = mapped_column(String(500))
    frequency: Mapped[RecurringFrequency] = mapped_column(
        SAEnum(RecurringFrequency), default=RecurringFrequency.monthly
    )
    next_run: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    envelope: Mapped["Envelope"] = relationship(back_populates="recurring_txns")


class Goal(TimestampMixin, Base):
    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    envelope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("envelopes.id"))
    name: Mapped[str] = mapped_column(String(200))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    target_date: Mapped[date | None] = mapped_column(Date)

    # Relationships
    envelope: Mapped["Envelope"] = relationship(back_populates="goals")


class NotificationType(str, enum.Enum):
    budget_warning = "budget_warning"
    subscription_due = "subscription_due"
    daily_summary = "daily_summary"
    weekly_summary = "weekly_summary"
    cooling_ready = "cooling_ready"
    system = "system"


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    type: Mapped[NotificationType] = mapped_column(
        SAEnum(NotificationType), default=NotificationType.system
    )
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(String(1000))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user: Mapped["User"] = relationship()


class NotificationPreference(TimestampMixin, Base):
    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    budget_warning_tg: Mapped[bool] = mapped_column(Boolean, default=True)
    budget_warning_web: Mapped[bool] = mapped_column(Boolean, default=True)
    subscription_due_tg: Mapped[bool] = mapped_column(Boolean, default=True)
    subscription_due_web: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_summary_tg: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_summary_web: Mapped[bool] = mapped_column(Boolean, default=False)
    weekly_summary_tg: Mapped[bool] = mapped_column(Boolean, default=True)
    weekly_summary_web: Mapped[bool] = mapped_column(Boolean, default=True)
    cooling_ready_tg: Mapped[bool] = mapped_column(Boolean, default=True)
    cooling_ready_web: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_summary_time: Mapped[str | None] = mapped_column(String(5), default="20:00")
    weekly_summary_time: Mapped[str | None] = mapped_column(String(5), default="08:00")

    user: Mapped["User"] = relationship()


class PendingTransactionStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    expired = "expired"


class PendingTransaction(TimestampMixin, Base):
    __tablename__ = "pending_transactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    envelope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("envelopes.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    description: Mapped[str] = mapped_column(String(500))
    source: Mapped[TransactionSource] = mapped_column(
        SAEnum(TransactionSource), default=TransactionSource.telegram
    )
    status: Mapped[PendingTransactionStatus] = mapped_column(
        SAEnum(PendingTransactionStatus), default=PendingTransactionStatus.pending
    )
    cooling_hours: Mapped[int] = mapped_column(Integer, default=24)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirm_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Relationships
    envelope: Mapped["Envelope"] = relationship()
    user: Mapped["User"] = relationship()


class MonthlySnapshot(TimestampMixin, Base):
    __tablename__ = "monthly_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    envelope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("envelopes.id"))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0")
    )
    closing_balance: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0")
    )
    rollover_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0")
    )

    # Relationships
    envelope: Mapped["Envelope"] = relationship(back_populates="monthly_snapshots")


class PaymentOrder(TimestampMixin, Base):
    __tablename__ = "payment_orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    original_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    promo_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    discount_pct: Mapped[int] = mapped_column(default=0)
    payment_method: Mapped[str] = mapped_column(String(50), default="manual_transfer")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    proof_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    admin_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    midtrans_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    user: Mapped["User"] = relationship()


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    discount_pct: Mapped[int] = mapped_column(default=0)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False)
    max_uses: Mapped[int | None] = mapped_column(nullable=True)
    used_count: Mapped[int] = mapped_column(default=0)
    valid_from: Mapped[datetime | None] = mapped_column(nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(nullable=True)
    event_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
