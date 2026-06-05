"""Configuração da aplicação.

Tudo é parametrizável por variáveis de ambiente para facilitar o deploy.
Para produção, defina obrigatoriamente SECRET_KEY.
"""
import os

basedir = os.path.abspath(os.path.dirname(__file__))
instance_dir = os.path.join(basedir, "instance")


class Config:
    # --- Segurança ---
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-troque-em-producao")

    # --- Banco de dados (SQLite por padrão, para portabilidade inicial) ---
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + os.path.join(instance_dir, "ir_traders.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Upload de notas de corretagem ---
    UPLOAD_FOLDER = os.path.join(instance_dir, "uploads")
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB por arquivo
    ALLOWED_EXTENSIONS = {"pdf"}

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
