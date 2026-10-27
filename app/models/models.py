import uuid
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import (
    String, Text, Numeric, Boolean, Integer, Date, DateTime,
    ForeignKey, Enum as SAEnum, func, UniqueConstraint, JSON, Index, text
)
from sqlalchemy.dialects.postgresql import JSONB
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


class PurposeType(str, enum.Enum):
    expense = "expense"
    saving = "saving"
    sinking_fund = "sinking_fund"
    debt = "debt"


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
    # Kolom whatsapp_id & phone masih ada di DB (fitur WhatsApp dihapus Okt 2026,
    # sengaja tanpa migrasi) — tidak dipetakan lagi di model.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    google_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(30), default="Asia/Jakarta")
    profile_pic: Mapped[str | None] = mapped_column(String(500), nullable=True)
    default_cooling_threshold: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    default_daily_limit: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    default_is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    plan: Mapped[str | None] = mapped_column(String(10), default="basic")
    payday_day: Mapped[int] = mapped_column(Integer, default=1)
    income_type: Mapped[str] = mapped_column(String(20), default="monthly")
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Diisi saat logout-all. Token lama tanpa `sid` (sebelum auth_sessions) tidak
    # punya iat, jadi semuanya ditolak bila kolom ini terisi.
    tokens_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    household_memberships: Mapped[list["HouseholdMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user")
    incomes: Mapped[list["Income"]] = relationship(back_populates="user")


class AuthSession(TimestampMixin, Base):
    """Satu sesi login per perangkat (ADR-M7). Refresh token membawa `sid` + `jti`;
    hanya `refresh_jti` yang berlaku, `prev_refresh_jti` diterima sebentar setelah
    rotasi (masa tenggang). Lihat app/services/auth_sessions.py."""
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    refresh_jti: Mapped[str] = mapped_column(String(64))
    prev_refresh_jti: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # sha256 refresh token lama (tanpa sid) yang ditukar jadi sesi ini; mencegah
    # token lama yang sama dipakai ulang membuka sesi kedua. Bisa dibuang setelah
    # semua token lama kedaluwarsa (30 hari sejak deploy).
    legacy_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client: Mapped[str | None] = mapped_column(String(100), nullable=True)  # X-Jatahku-Client
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)


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
    # AI Advisor Fase 5 (02-aturan.md §3): "harian" | "bulanan" | None = otomatis (purpose debt →
    # bulanan, selain itu harian). Hanya amplop harian yang membentuk jatah harian.
    jenis: Mapped[str | None] = mapped_column(String(10), nullable=True)

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
    purpose: Mapped[str] = mapped_column(
        String(20), default="expense", nullable=False, server_default="expense"
    )
    classification: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default=None
    )
    # Dana darurat (AI Advisor G8/TAB-01). Backfill dari nama saat migrasi, lalu diatur user.
    is_emergency: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )

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
    is_private: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    # Terisi = penyesuaian "cocokkan saldo" (spec 2026-09-30), bukan input user.
    balance_check_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("balance_checks.id"), nullable=True, index=True, default=None
    )

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
    # Terisi = income penyesuaian "cocokkan saldo" (bukan pemasukan sungguhan).
    balance_check_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("balance_checks.id"), nullable=True, index=True, default=None
    )

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


class BalanceCheck(TimestampMixin, Base):
    """Satu kali "Cocokkan saldo": uang riil vs angka app. Penyesuaiannya adalah
    Transaction/Income biasa yang menunjuk ke sini lewat balance_check_id."""
    __tablename__ = "balance_checks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    actual_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    app_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    gap: Mapped[Decimal] = mapped_column(Numeric(15, 2))  # actual - app
    undone_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


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
    payday_reminder_tg: Mapped[bool] = mapped_column(Boolean, default=True)
    checkin_nudge_tg: Mapped[bool] = mapped_column(Boolean, default=True)
    checkin_nudge_time: Mapped[str | None] = mapped_column(String(5), default="21:00")
    daily_summary_time: Mapped[str | None] = mapped_column(String(5), default="20:00")
    weekly_summary_time: Mapped[str | None] = mapped_column(String(5), default="08:00")

    user: Mapped["User"] = relationship()


class UserStreak(TimestampMixin, Base):
    """Tracks how consistently a user logs activity (the discipline framework).

    A "logged day" is any day the user either records a transaction or
    explicitly marks as a no-spending day — both keep the streak alive, so
    discipline means *showing up*, not spending money. All dates are stored in
    the user's local timezone (resolved when activity is recorded)."""
    __tablename__ = "user_streaks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0)
    total_logged_days: Mapped[int] = mapped_column(Integer, default=0)
    # Last local date the user logged activity (kept the streak alive).
    last_log_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Last local date a check-in nudge was sent (anti-spam: max once/day).
    last_checkin_date: Mapped[date | None] = mapped_column(Date, nullable=True)

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
    is_private: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
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

    __table_args__ = (
        UniqueConstraint("envelope_id", "year", "month", name="uq_snapshot_envelope_period"),
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


class UserEnvelopeKeyword(Base):
    __tablename__ = "user_envelope_keywords"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    keyword: Mapped[str] = mapped_column(String(100))
    envelope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("envelopes.id", ondelete="CASCADE"))
    count: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (UniqueConstraint("user_id", "keyword", "envelope_id", name="uq_user_kw_env"),)


class GlobalIntentPhrase(Base):
    """User-confirmed phrase → intent mappings, shared across all users."""
    __tablename__ = "global_intent_phrases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    phrase: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    intent: Mapped[str] = mapped_column(String(50))
    count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# --- Scan struk (OCR tanpa LLM) ---

class ReceiptScan(Base):
    """Satu kali scan struk. Dipakai untuk kuota bulanan, metrik akurasi, dan
    belajar dari koreksi. Teks OCR (ocr_lines) dihapus setelah feedback diproses."""
    __tablename__ = "receipt_scans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    engine: Mapped[str] = mapped_column(String(20), default="rapidocr")  # rapidocr | llm
    merchant: Mapped[str | None] = mapped_column(String(100), nullable=True)
    merchant_key: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    parsed_total: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    parsed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    confidence: Mapped[str] = mapped_column(String(10), default="gagal")
    total_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ocr_lines: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list; dikosongkan setelah feedback
    final_total: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    final_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    final_merchant: Mapped[str | None] = mapped_column(String(100), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(12), nullable=True)  # accepted | corrected | discarded
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Kotak Struk ("Bagikan ke Jatahku"; spec 2026-10-26 §2a). Semua nullable
    # kecuali attempts; status NULL = baris lama (riwayat scan). DDL Postgres-nya
    # ada di app/services/kotak_struk/schema.py (KOTAK_DDL).
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # telegram | web_chat | web_form | pwa_share
    status: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)  # diterima | diproses | siap | gagal | tercatat | dilewati | kedaluwarsa
    doc_type: Mapped[str | None] = mapped_column(String(30), nullable=True)  # struk_belanja | qris | transfer | tidak_dikenali
    household_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    upload_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # unik per user (indeks parsial uq_receipt_scans_upload)
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    content_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)  # dikosongkan saat file dihapus
    ref_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # HMAC nomor referensi
    counterparty_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)  # Dokumen Bayar
    parser: Mapped[str | None] = mapped_column(String(40), nullable=True)  # mis. qris.umum
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)  # alasan gagal yang aman ditampilkan
    channel_meta: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transaction_ids: Mapped[list | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)

    # Satu unggahan (upload_id dari klien) hanya satu item per user. Nama sama dengan di
    # KOTAK_DDL, jadi DDL startup tidak membuat indeks ganda di basis data baru.
    __table_args__ = (
        Index("uq_receipt_scans_upload", "user_id", "upload_id", unique=True,
              postgresql_where=text("upload_id IS NOT NULL"), sqlite_where=text("upload_id IS NOT NULL")),
    )


class ReceiptTotalLabel(Base):
    """Profil toko (dipakai bersama semua user): label baris yang berisi total
    akhir, dipelajari dari koreksi. Contoh: INDOMARET → "TOTAL BELANJA"."""
    __tablename__ = "receipt_total_labels"

    merchant_key: Mapped[str] = mapped_column(String(60), primary_key=True)
    label: Mapped[str] = mapped_column(String(100), primary_key=True)
    hits: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ReceiptMerchantAlias(Base):
    """Nama toko salah-baca OCR → nama yang benar (dari koreksi user)."""
    __tablename__ = "receipt_merchant_aliases"

    raw_key: Mapped[str] = mapped_column(String(60), primary_key=True)
    merchant: Mapped[str] = mapped_column(String(100))
    hits: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ReceiptLearnVote(Base):
    """Satu suara per user untuk tiap hal yang dipelajari (label total / alias toko).
    Data belajar baru dipakai setelah disetujui ≥ 2 user BERBEDA, supaya satu
    user tidak bisa mengubah hasil scan user lain."""
    __tablename__ = "receipt_learn_votes"

    kind: Mapped[str] = mapped_column(String(10), primary_key=True)  # label | alias
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HouseholdMerchant(Base):
    """Pihak penerima yang pernah muncul di bukti bayar sebuah rumah tangga
    (spec 2026-10-26 §2c). counterparty_key: nmid:<NMID> | nama:<nama>|<kota> |
    rek:<hmac>; nomor rekening tidak pernah disimpan utuh."""
    __tablename__ = "household_merchants"
    __table_args__ = (UniqueConstraint("household_id", "counterparty_key", name="uq_hh_merchant"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    counterparty_key: Mapped[str] = mapped_column(String(80))
    raw_name: Mapped[str] = mapped_column(String(100))  # nama di bukti terakhir
    display_name: Mapped[str | None] = mapped_column(String(60), nullable=True)  # nama panggilan dari user
    city: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MerchantEnvelopeMap(Base):
    """Peta merchant → amplop per rumah tangga: berapa kali amplop itu dipilih
    untuk merchant itu. Dasar saran amplop (spec 2026-10-26 §4)."""
    __tablename__ = "merchant_envelope_map"
    __table_args__ = (UniqueConstraint("merchant_id", "envelope_id", name="uq_merchant_env"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("household_merchants.id", ondelete="CASCADE"))
    envelope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("envelopes.id", ondelete="CASCADE"))
    count: Mapped[int] = mapped_column(Integer, default=1)
    last_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
