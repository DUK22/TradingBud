"""Importação de notas de corretagem direto de uma caixa de e-mail (IMAP).

Fluxo (rodado por cron via `flask import-mail`):
  1. Conecta na caixa configurada (IMPORT_IMAP_*) e busca mensagens NÃO LIDAS.
  2. Para cada mensagem, identifica o usuário pelo e-mail do REMETENTE
     (precisa ser o mesmo e-mail da conta no app).
  3. Extrai os anexos PDF e importa pelo pipeline comum (OCR + dedupe) —
     duplicatas são ignoradas, então encaminhar duas vezes não duplica nada.

Como o usuário usa: encaminha o e-mail da corretora (com a nota anexa) para a
caixa configurada, a partir do e-mail cadastrado no app. Configuração:

    IMPORT_IMAP_HOST     (ex.: imap.gmail.com — sem ele, o recurso fica off)
    IMPORT_IMAP_PORT     (padrão 993, SSL)
    IMPORT_IMAP_USER / IMPORT_IMAP_PASSWORD
    IMPORT_IMAP_FOLDER   (padrão INBOX)

Segurança: mensagens de remetentes desconhecidos são apenas marcadas como
lidas e ignoradas (nunca processadas). PDFs cifrados/corrompidos contam como
erro e não interrompem o lote.
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import logging
import os

log = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(os.environ.get("IMPORT_IMAP_HOST"))


def _connect() -> imaplib.IMAP4_SSL:
    host = os.environ["IMPORT_IMAP_HOST"]
    port = int(os.environ.get("IMPORT_IMAP_PORT", "993"))
    conn = imaplib.IMAP4_SSL(host, port)
    conn.login(os.environ.get("IMPORT_IMAP_USER", ""),
               os.environ.get("IMPORT_IMAP_PASSWORD", ""))
    conn.select(os.environ.get("IMPORT_IMAP_FOLDER", "INBOX"))
    return conn


def _pdf_attachments(msg) -> list[tuple[str, bytes]]:
    out = []
    for part in msg.walk():
        fname = part.get_filename() or ""
        ctype = (part.get_content_type() or "").lower()
        if ctype == "application/pdf" or fname.lower().endswith(".pdf"):
            raw = part.get_payload(decode=True)
            if raw and raw[:5] == b"%PDF-":
                out.append((fname or "nota.pdf", raw))
    return out


def fetch_messages() -> list[dict]:
    """Busca mensagens não lidas e devolve
    [{'sender': str, 'subject': str, 'pdfs': [(nome, bytes), ...]}, ...].
    As mensagens ficam marcadas como lidas (não são reprocessadas)."""
    conn = _connect()
    try:
        _, data = conn.search(None, "UNSEEN")
        ids = data[0].split() if data and data[0] else []
        out = []
        for msg_id in ids:
            _, fetched = conn.fetch(msg_id, "(RFC822)")   # fetch marca \\Seen
            if not fetched or not fetched[0]:
                continue
            msg = email.message_from_bytes(fetched[0][1])
            sender = email.utils.parseaddr(msg.get("From", ""))[1].lower().strip()
            out.append({
                "sender": sender,
                "subject": str(msg.get("Subject", ""))[:120],
                "pdfs": _pdf_attachments(msg),
            })
        return out
    finally:
        try:
            conn.close()
            conn.logout()
        except Exception:  # noqa: BLE001
            log.debug("Falha ao encerrar a conexão IMAP (ignorada).")
