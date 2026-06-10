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


def _resolve_cpf_enc_key() -> str | None:
    """Chave Fernet (urlsafe-base64, 32 bytes) p/ criptografar o CPF em repouso.

    Gere com:
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    Em produção é OBRIGATÓRIA (se trocar/perder, os CPFs já gravados ficam
    ilegíveis). Em dev, ausência => o módulo de cripto usa um fallback fixo."""
    key = os.environ.get("CPF_ENC_KEY")
    if not key and IS_PRODUCTION:
        raise RuntimeError(
            "CPF_ENC_KEY não definida. Defina-a (chave Fernet) antes de subir "
            "em produção — o CPF é criptografado em repouso (LGPD)."
        )
    return key


class Config:
    # --- Segurança ---
    SECRET_KEY = _resolve_secret_key()
    CPF_ENC_KEY = _resolve_cpf_enc_key()

    # Cookies de sessão: HttpOnly sempre; Secure só em produção (exige HTTPS).
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = IS_PRODUCTION
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = IS_PRODUCTION

    # Rate limiting (Flask-Limiter). Em produção use Redis: redis://host:6379
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    # --- Banco de dados (SQLite por padrão; PostgreSQL em produção) ---
    _db_url = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + os.path.join(instance_dir, "ir_traders.db")
    )
    # Provedores (Render/Heroku) usam o esquema antigo "postgres://"; o
    # SQLAlchemy 2.x exige "postgresql://".
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Upload de notas de corretagem ---
    UPLOAD_FOLDER = os.path.join(instance_dir, "uploads")
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB por arquivo
    ALLOWED_EXTENSIONS = {"pdf"}

    # --- Paginação das listagens (notas, negócios) ---
    ITEMS_PER_PAGE = int(os.environ.get("ITEMS_PER_PAGE", "25"))

    # --- Estimativa de custos da nota provisória (% sobre o volume) ---
    # ~0,03% cobre emolumentos + liquidação da B3 de forma aproximada.
    B3_COST_RATE = os.environ.get("B3_COST_RATE", "0.0003")

    # --- Cotações (brapi.dev) — opcional ---
    # Sem token, o fallback é o Yahoo Finance (não-oficial). Tokens gratuitos
    # em https://brapi.dev/dashboard
    BRAPI_TOKEN = os.environ.get("BRAPI_TOKEN")

    # --- IA (insights do diário) — opcional ---
    # Sem ANTHROPIC_API_KEY o recurso fica desabilitado (degrada com aviso).
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
    # Padrão: modelo mais capaz. Para reduzir custo, defina ANTHROPIC_MODEL=claude-haiku-4-5
    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")

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
