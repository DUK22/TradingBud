"""Configuração da aplicação.

Tudo é parametrizável por variáveis de ambiente para facilitar o deploy.
Para produção (FLASK_ENV=production), defina obrigatoriamente SECRET_KEY — a
app aborta a inicialização se ela estiver ausente.
"""
import os
import secrets

basedir = os.path.abspath(os.path.dirname(__file__))
instance_dir = os.path.join(basedir, "instance")

IS_PRODUCTION = os.environ.get("FLASK_ENV", "development").lower() == "production"


def _resolve_secret_key() -> str:
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    if IS_PRODUCTION:
        raise RuntimeError(
            "SECRET_KEY não definida. Defina a variável de ambiente SECRET_KEY "
            "antes de subir em produção (FLASK_ENV=production)."
        )
    # Dev: gera uma chave efêmera (sessões caem ao reiniciar — aceitável em dev).
    return "dev-" + secrets.token_hex(16)


class Config:
    # --- Segurança ---
    SECRET_KEY = _resolve_secret_key()

    # Cookies de sessão: HttpOnly sempre; Secure só em produção (exige HTTPS).
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = IS_PRODUCTION
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = IS_PRODUCTION

    # Rate limiting (Flask-Limiter). Em produção use Redis: redis://host:6379
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    # --- Banco de dados (SQLite por padrão, para portabilidade inicial) ---
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + os.path.join(instance_dir, "ir_traders.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Upload de notas de corretagem ---
    UPLOAD_FOLDER = os.path.join(instance_dir, "uploads")
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB por arquivo
    ALLOWED_EXTENSIONS = {"pdf"}

    # --- Paginação das listagens (notas, negócios) ---
    ITEMS_PER_PAGE = int(os.environ.get("ITEMS_PER_PAGE", "25"))

    # --- Integração futura com a B3 (Área do Investidor) ---
    # Placeholders: a API oficial ainda exige convênio/credenciais.
    B3_API_BASE_URL = os.environ.get("B3_API_BASE_URL", "https://investidor.b3.com.br/api/v1")
    B3_CLIENT_ID = os.environ.get("B3_CLIENT_ID", "")
    B3_CLIENT_SECRET = os.environ.get("B3_CLIENT_SECRET", "")
    B3_ENABLED = os.environ.get("B3_ENABLED", "0") == "1"


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
