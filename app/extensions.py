"""Extensões Flask compartilhadas (evita import circular)."""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Faça login para acessar esta página."
login_manager.login_message_category = "warning"

# Proteção CSRF para TODAS as rotas POST (inclusive as que leem request.form
# direto, que não passam por FlaskForm.validate_on_submit()).
csrf = CSRFProtect()

# Rate limiting (anti brute-force). Default vazio; limites específicos são
# aplicados por rota (ex.: login). Em produção, defina RATELIMIT_STORAGE_URI
# (Redis) para funcionar com múltiplos workers.
limiter = Limiter(key_func=get_remote_address, default_limits=[])
