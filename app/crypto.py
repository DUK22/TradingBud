"""Criptografia em repouso para dados sensíveis (CPF) — LGPD.

Usa Fernet (AES-128-CBC + HMAC, da biblioteca `cryptography`). A chave vem de
CPF_ENC_KEY (chave Fernet urlsafe-base64). Em dev, na ausência da chave, usa um
fallback FIXO e determinístico (apenas para os dados de teste persistirem entre
reinícios — NÃO use em produção; lá a chave é obrigatória, ver config.py).

A coluna EncryptedString é transparente: o app continua lendo/escrevendo o CPF
em texto puro; a (de)criptografia acontece no boundary do banco.
"""
import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

log = logging.getLogger(__name__)

_DEV_FALLBACK_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(b"ir-traders-dev-cpf-key").digest()
)


def _resolve_key() -> bytes:
    key = None
    try:
        from flask import current_app
        key = current_app.config.get("CPF_ENC_KEY")
    except RuntimeError:
        # Fora de um app context: cai para a variável de ambiente.
        key = os.environ.get("CPF_ENC_KEY")
    if not key:
        return _DEV_FALLBACK_KEY
    return key.encode() if isinstance(key, str) else key


def _fernet() -> Fernet:
    return Fernet(_resolve_key())


class EncryptedString(TypeDecorator):
    """Coluna de texto criptografada em repouso (transparente para o app)."""

    impl = String(255)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or value == "":
            return value
        return _fernet().encrypt(str(value).encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None or value == "":
            return value
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            log.warning("Valor criptografado ilegível (CPF_ENC_KEY trocada/ausente?).")
            return None
