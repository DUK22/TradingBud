"""Application factory.

Cria a app Flask, inicializa extensões (SQLAlchemy, Login), registra os
blueprints (auth e main) e garante a criação do schema SQLite.
"""
import logging
import logging.config
import os

from flask import Flask

from config import Config, basedir, instance_dir

from .extensions import csrf, db, limiter, login_manager, migrate
from .utils import register_filters

log = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.join(basedir, "migrations")


def _configure_logging():
    """Logging centralizado p/ stdout (LOG_LEVEL configurável). Sob gunicorn,
    os logs da app saem junto com os do servidor — prontos p/ agregadores."""
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {"format": "%(asctime)s %(levelname)s [%(name)s] %(message)s"},
        },
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": "default"},
        },
        "root": {"level": level, "handlers": ["console"]},
    })


# Content-Security-Policy: CSS local; Chart.js via jsdelivr; widget de gráfico
# em tempo real do TradingView (script de s3 + iframe de tradingview.com).
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://s3.tradingview.com; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https://*.tradingview.com; "
    "connect-src 'self' https://*.tradingview.com wss://*.tradingview.com; "
    "frame-src https://www.tradingview.com https://s.tradingview.com https://www.tradingview-widget.com; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def _register_security_headers(app):
    @app.after_request
    def _set_headers(resp):
        resp.headers.setdefault("Content-Security-Policy", _CSP)
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if app.config.get("SESSION_COOKIE_SECURE"):
            resp.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp


def _init_schema(app):
    """Garante o schema do banco.

    - Testes (in-memory): cria as tabelas direto via create_all().
    - Demais ambientes: aplica as migrações Alembic (flask db upgrade) — assim
      a evolução do schema é versionada e auditável (substitui o antigo
      create_all() + ALTER TABLE manual).

    Defina SKIP_SCHEMA_INIT=1 para pular este passo (ex.: ao rodar os próprios
    comandos `flask db ...`, evitando efeitos colaterais na autogeração)."""
    if os.environ.get("SKIP_SCHEMA_INIT") == "1":
        return
    with app.app_context():
        if app.config.get("TESTING"):
            db.create_all()
            return
        from flask_migrate import upgrade
        try:
            upgrade()
        except Exception:  # noqa: BLE001
            # Fallback p/ não derrubar a app; registra para diagnóstico.
            log.exception("Falha ao aplicar migrações; usando create_all() de fallback.")
            db.create_all()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    if not app.config.get("TESTING"):
        _configure_logging()

    # Atrás de um proxy (Render/Heroku/Nginx) que termina o TLS: confia nos
    # cabeçalhos X-Forwarded-* para enxergar https/host corretos.
    if app.config.get("SESSION_COOKIE_SECURE"):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Garante diretórios de instância/uploads
    os.makedirs(instance_dir, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # Extensões
    db.init_app(app)
    from . import models  # noqa: F401  (registra os modelos p/ o Alembic autogenerate)
    migrate.init_app(app, db, directory=MIGRATIONS_DIR)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # Cabeçalhos de segurança (CSP, X-Frame-Options, HSTS em prod, ...)
    _register_security_headers(app)

    # User loader
    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Blueprints
    from .auth import auth_bp
    from .main import main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    # Filtros Jinja (formatação pt-BR)
    register_filters(app)

    # Handlers amigáveis: CSRF inválido (400) e limite de requisições (429)
    from flask import flash, redirect, request, url_for
    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def _handle_csrf(e):
        flash("Sessão expirada ou formulário inválido. Tente novamente.", "error")
        return redirect(request.referrer or url_for("main.dashboard")), 400

    @app.errorhandler(429)
    def _handle_ratelimit(e):
        flash("Muitas tentativas em pouco tempo. Aguarde um instante e tente de novo.", "error")
        return redirect(request.referrer or url_for("auth.login")), 429

    # Schema (migrações Alembic; create_all apenas em testes)
    _init_schema(app)

    return app
