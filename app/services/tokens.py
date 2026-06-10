"""Tokens assinados (stateless) para verificação de e-mail e reset de senha.

Usa itsdangerous (dependência do próprio Flask) com a SECRET_KEY da app e
salts distintos por finalidade. O token carrega o id do usuário e expira."""
from __future__ import annotations

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SALT_VERIFY = "email-verify"
SALT_RESET = "password-reset"
MAX_AGE_VERIFY = 60 * 60 * 24 * 7   # 7 dias
MAX_AGE_RESET = 60 * 60             # 1 hora


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=salt)


def generate(user_id: int, salt: str) -> str:
    return _serializer(salt).dumps({"uid": user_id})


def verify(token: str, salt: str, max_age: int) -> int | None:
    """Devolve o user_id do token, ou None se inválido/expirado."""
    try:
        data = _serializer(salt).loads(token, max_age=max_age)
        return int(data["uid"])
    except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
        return None
