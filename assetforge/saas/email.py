"""Отправка email с подключаемым backend'ом (console / smtp).

В dev по умолчанию `console` — письма печатаются в лог, реальная почта не нужна.
Для прода: ASSETFORGE_EMAIL=smtp + SMTP_* переменные.
"""
from __future__ import annotations

from email.message import EmailMessage

from .config import settings


def send_email(to: str, subject: str, body: str) -> None:
    backend = settings.email_backend
    if backend == "smtp" and settings.smtp_host:
        _send_smtp(to, subject, body)
    else:
        _send_console(to, subject, body)


def _send_console(to: str, subject: str, body: str) -> None:
    text = f"\n[email->console] to={to}\n  subject: {subject}\n  {body}\n"
    try:
        print(text)
    except UnicodeEncodeError:                      # консоль Windows (cp1251) не тянет часть юникода
        import sys
        enc = (sys.stdout.encoding or "utf-8")
        print(text.encode(enc, "replace").decode(enc))


def _send_smtp(to: str, subject: str, body: str) -> None:
    import smtplib

    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as srv:
        srv.starttls()
        if settings.smtp_user:
            srv.login(settings.smtp_user, settings.smtp_password)
        srv.send_message(msg)
