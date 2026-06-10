"""Envio de e-mails transacionais (verificação de conta, reset de senha).

Configuração por variáveis de ambiente (qualquer provedor SMTP — Gmail,
SendGrid, Mailgun, Amazon SES...):

    MAIL_SERVER   (ex.: smtp.sendgrid.net) — sem ele, modo DEV: loga o e-mail
    MAIL_PORT     (padrão 587)
    MAIL_USERNAME / MAIL_PASSWORD
    MAIL_USE_TLS  (padrão 1 — STARTTLS)
    MAIL_FROM     (padrão MAIL_USERNAME)

Sem MAIL_SERVER, o conteúdo é registrado no log (nível INFO) — útil em dev
para copiar o link sem precisar de um servidor de e-mail.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(os.environ.get("MAIL_SERVER"))


def send(to: str, subject: str, body: str) -> bool:
    """Envia (ou loga, em dev) um e-mail texto-plano. Retorna sucesso."""
    if not is_configured():
        log.info("MAIL (dev, não enviado) para=%s assunto=%r\n%s", to, subject, body)
        return True

    server = os.environ["MAIL_SERVER"]
    port = int(os.environ.get("MAIL_PORT", "587"))
    username = os.environ.get("MAIL_USERNAME", "")
    password = os.environ.get("MAIL_PASSWORD", "")
    use_tls = os.environ.get("MAIL_USE_TLS", "1") == "1"
    sender = os.environ.get("MAIL_FROM") or username

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(server, port, timeout=10) as smtp:
            if use_tls:
                smtp.starttls()
            if username:
                smtp.login(username, password)
            smtp.send_message(msg)
        return True
    except Exception:  # noqa: BLE001
        log.exception("Falha ao enviar e-mail para %s", to)
        return False
