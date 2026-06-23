"""ORM-модели SaaS (SQLAlchemy 2.0)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120), default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str] = mapped_column(String(20), default="user")   # user | support | admin | superadmin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)   # False = заблокирован
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verify_token: Mapped[str] = mapped_column(String(64), default="")
    reset_token: Mapped[str] = mapped_column(String(64), default="")
    # двухфакторная аутентификация (TOTP) — для сотрудников
    totp_secret: Mapped[str] = mapped_column(String(64), default="")
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # «эпоха» сессии: инкремент инвалидирует все активные cookie-сессии (force logout)
    session_epoch: Mapped[int] = mapped_column(Integer, default=0)

    # текущий тариф: вычисляемый «эффективный» план = plan_id, пока now < plan_until (или free)
    plan_id: Mapped[str] = mapped_column(String(40), default="free")
    plan_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # продлевать ли подписку (для будущего рекуррента); False = доступ до plan_until, без продления
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(String(2000), default="")      # заметки админа
    # реферальная программа
    referral_code: Mapped[str] = mapped_column(String(16), default="", index=True)
    referred_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    referral_rewarded: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    payments: Mapped[list["Payment"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    usage: Mapped[list["UsageRecord"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    def effective_plan(self, now: datetime | None = None) -> str:
        now = now or utcnow()
        if self.plan_id != "free" and self.plan_until and _aware(self.plan_until) > now:
            return self.plan_id
        return "free"

    # --- роли сотрудников (RBAC) ---
    @property
    def is_staff(self) -> bool:
        return self.role in ("support", "admin", "superadmin") or self.is_admin

    @property
    def can_write(self) -> bool:
        """Может ли менять данные в админке (support — только чтение)."""
        return self.role in ("admin", "superadmin")

    @property
    def is_superadmin(self) -> bool:
        return self.role == "superadmin"


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(30))
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|paid|failed|canceled
    external_id: Mapped[str] = mapped_column(String(128), default="")    # id в системе провайдера
    promo_code: Mapped[str] = mapped_column(String(40), default="")
    period_days: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="payments")


class UsageRecord(Base):
    """Помесячный счётчик использования (квоты тарифа)."""
    __tablename__ = "usage_records"
    __table_args__ = (UniqueConstraint("user_id", "period", name="uq_usage_user_period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))   # 'YYYY-MM'
    exports: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped["User"] = relationship(back_populates="usage")


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(20))     # percent | free_days | grant_plan
    value: Mapped[float] = mapped_column(Float, default=0.0)  # % скидки или кол-во дней
    plan_id: Mapped[str] = mapped_column(String(40), default="pro")
    max_uses: Mapped[int] = mapped_column(Integer, default=0)  # 0 = безлимит
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def is_valid(self, now: datetime | None = None) -> bool:
        now = now or utcnow()
        if not self.active:
            return False
        if self.expires_at and _aware(self.expires_at) < now:
            return False
        if self.max_uses and self.used_count >= self.max_uses:
            return False
        return True


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (UniqueConstraint("user_id", "code", name="uq_promo_user_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Журнал действий администратора (кто, что, над кем, когда)."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    admin_email: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(60))          # напр. user.grant_plan
    target: Mapped[str] = mapped_column(String(120), default="")  # напр. user:42
    detail: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AppSetting(Base):
    """Настройки приложения, изменяемые из админки (без передеплоя)."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), default="")


class ApiKey(Base):
    """API-ключ пользователя для интеграций (хранится только хэш)."""
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    prefix: Mapped[str] = mapped_column(String(16), index=True)   # видимая часть (af_xxxx)
    key_hash: Mapped[str] = mapped_column(String(64))             # sha256 полного ключа
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookEvent(Base):
    """Журнал входящих платёжных вебхуков (для отладки и аудита)."""
    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20), default="")
    payment_id: Mapped[int | None] = mapped_column(nullable=True)
    external_id: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class LoginEvent(Base):
    """Журнал попыток входа (успех/неуспех + IP) — безопасность и поддержка."""
    __tablename__ = "login_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(20), default="login")   # login | 2fa | admin
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class DesktopRelease(Base):
    """Релиз desktop-приложения, управляемый из админки (файл + версия + заметки)."""
    __tablename__ = "desktop_releases"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(40), index=True)
    notes: Mapped[str] = mapped_column(String(2000), default="")
    filename: Mapped[str] = mapped_column(String(255), default="")    # имя файла в каталоге релизов
    size: Mapped[int] = mapped_column(Integer, default=0)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class VersionStat(Base):
    """Статистика установленных версий (по пингам обновления)."""
    __tablename__ = "version_stats"

    version: Mapped[str] = mapped_column(String(40), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FeatureFlag(Base):
    """A/B-флаг: процент выката (0..100) + общий выключатель."""
    __tablename__ = "feature_flags"

    name: Mapped[str] = mapped_column(String(60), primary_key=True)
    rollout: Mapped[int] = mapped_column(Integer, default=0)          # % пользователей
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def _aware(dt: datetime) -> datetime:
    """SQLite может вернуть naive datetime — трактуем как UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
