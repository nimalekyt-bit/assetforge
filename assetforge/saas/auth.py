"""Регистрация, вход, сессии и зависимости доступа."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .email import send_email
from .models import User
from .security import hash_password, new_token, valid_email, valid_password, verify_password


# --- операции ---------------------------------------------------------------

def register(db: Session, email: str, password: str, name: str = "", ref_code: str = "") -> User:
    email = (email or "").strip().lower()
    if not valid_email(email):
        raise HTTPException(400, "Некорректный email.")
    ok, why = valid_password(password or "")
    if not ok:
        raise HTTPException(400, why)
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Пользователь с таким email уже существует.")

    # реферал: кто пригласил (по referral_code)
    referrer = None
    if ref_code:
        referrer = db.scalar(select(User).where(User.referral_code == ref_code.strip()))

    # роль/админ: назначаем ТОЛЬКО если ASSETFORGE_ADMIN_EMAIL задан явно и совпадает
    is_admin = settings.admin_email_set and email == settings.admin_email.strip().lower()
    user = User(
        email=email,
        password_hash=hash_password(password),
        name=(name or "").strip(),
        is_admin=is_admin,
        role="superadmin" if is_admin else "user",
        verify_token=new_token(),
        email_verified=not settings.require_email_verification,
        referral_code=new_token(6)[:10],
        referred_by_id=referrer.id if referrer else None,
    )
    db.add(user)
    db.flush()
    _send_verification(user)
    _send_welcome(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    email = (email or "").strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user and verify_password(password, user.password_hash):
        return user
    return None


def change_password(db: Session, user: User, old_password: str, new_password: str) -> tuple[bool, str]:
    """Смена пароля из кабинета (нужен текущий пароль)."""
    if not verify_password(old_password or "", user.password_hash):
        return False, "Текущий пароль неверен."
    ok, why = valid_password(new_password or "")
    if not ok:
        return False, why
    if verify_password(new_password, user.password_hash):
        return False, "Новый пароль совпадает со старым."
    user.password_hash = hash_password(new_password)
    user.reset_token = ""
    return True, "Пароль изменён."


def update_profile(db: Session, user: User, name: str) -> None:
    user.name = (name or "").strip()[:120]


def delete_account(db: Session, user: User) -> None:
    """Удалить аккаунт пользователя (платежи/использование — каскадом по модели)."""
    db.delete(user)
    db.flush()


def verify_email(db: Session, token: str) -> bool:
    if not token:
        return False
    user = db.scalar(select(User).where(User.verify_token == token))
    if not user:
        return False
    user.email_verified = True
    user.verify_token = ""
    return True


def resend_verification(db: Session, user: User) -> None:
    """Сгенерировать новый токен и переотправить письмо подтверждения."""
    if user.email_verified:
        return
    user.verify_token = new_token()
    db.flush()
    _send_verification(user, force=True)


def start_password_reset(db: Session, email: str) -> None:
    """Выдать токен сброса пароля и отправить письмо. Молчит, если email не найден
    (не раскрываем наличие аккаунта)."""
    email = (email or "").strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        return
    user.reset_token = new_token()
    db.flush()
    link = f"{settings.base_url}/reset?token={user.reset_token}"
    _safe_send(user.email, "Сброс пароля AssetForge",
               f"Чтобы задать новый пароль, перейдите по ссылке: {link}\n"
               f"Если вы не запрашивали сброс — просто игнорируйте письмо.")


def reset_password(db: Session, token: str, new_password: str) -> tuple[bool, str]:
    """Сменить пароль по токену сброса. Возвращает (ok, сообщение)."""
    if not token:
        return False, "Ссылка недействительна."
    user = db.scalar(select(User).where(User.reset_token == token))
    if not user:
        return False, "Ссылка недействительна или уже использована."
    ok, why = valid_password(new_password or "")
    if not ok:
        return False, why
    user.password_hash = hash_password(new_password)
    user.reset_token = ""
    return True, "Пароль изменён. Войдите с новым паролем."


def _send_verification(user: User, force: bool = False) -> None:
    if not settings.require_email_verification and not force:
        return
    link = f"{settings.base_url}/verify?token={user.verify_token}"
    _safe_send(user.email, "Подтверждение AssetForge",
               f"Подтвердите регистрацию: {link}")


def _send_welcome(user: User) -> None:
    """Приветственное письмо после регистрации (graceful, не роняет регистрацию)."""
    _safe_send(user.email, "Добро пожаловать в AssetForge ⚒",
               "Спасибо за регистрацию!\n\n"
               f"Инструмент: {settings.base_url}/app\n"
               "Загрузите логотип — и заберите готовый набор иконок за секунды.\n\n"
               "Если будут вопросы — просто ответьте на это письмо.")


def _safe_send(to: str, subject: str, body: str) -> None:
    """Отправка письма, которая НЕ роняет запрос при сбое SMTP."""
    try:
        send_email(to, subject, body)
    except Exception as exc:  # noqa: BLE001
        from ..logging_setup import get_logger
        get_logger("auth").warning("не удалось отправить письмо на %s: %s", to, exc)


# --- сессии -----------------------------------------------------------------

def login_session(request: Request, user: User) -> None:
    request.session["uid"] = user.id
    request.session["epoch"] = user.session_epoch


def logout_session(request: Request) -> None:
    request.session.pop("uid", None)
    request.session.pop("epoch", None)


# --- зависимости ------------------------------------------------------------

def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    user = db.get(User, uid)
    if user is None:
        return None
    epoch = request.session.get("epoch")
    if epoch is not None and epoch != user.session_epoch:   # сессия принудительно завершена
        return None
    return user


def require_user(user: User | None = Depends(current_user)) -> User:
    if not user:
        raise HTTPException(401, "Требуется вход.")
    if not user.is_active:
        raise HTTPException(403, "Аккаунт заблокирован. Обратитесь в поддержку.")
    if settings.require_email_verification and not user.email_verified:
        raise HTTPException(403, "Подтвердите email, чтобы продолжить.")
    return user


def require_user_unverified(user: User | None = Depends(current_user)) -> User:
    """Как require_user, но НЕ требует подтверждённого email (для /verify/resend)."""
    if not user:
        raise HTTPException(401, "Требуется вход.")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_staff:
        raise HTTPException(403, "Только для администратора.")
    return user


def require_superadmin(user: User = Depends(require_admin)) -> User:
    if not user.is_superadmin:
        raise HTTPException(403, "Только для супер-администратора.")
    return user


def require_writer(user: User = Depends(require_admin)) -> User:
    """Действия, меняющие данные: support — только чтение."""
    if not user.can_write:
        raise HTTPException(403, "У вашей роли только просмотр (read-only).")
    return user
