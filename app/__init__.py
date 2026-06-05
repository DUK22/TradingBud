"""Application factory.

Cria a app Flask, inicializa extensões (SQLAlchemy, Login), registra os
blueprints (auth e main) e garante a criação do schema SQLite.
"""
import logging
import os
from flask import Flask

from config import Config, instance_dir
from .extensions import db, login_manager, csrf, limiter
from .utils import register_filters

log = logging.getLogger(__name__)


# Content-Security-Policy: a UI usa Tailwind e Chart.js via CDN, então liberamos
# esses hosts. Ao migrar para assets locais (build do Tailwind), troque por 'self'.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
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


def _ensure_bmf_columns():
    """Migração leve p/ SQLite: adiciona colunas BM&F se faltarem (sem Alembic)."""
    from sqlalchemy import inspect, text
    try:
        insp = inspect(db.engine)
        cols = {c["name"] for c in insp.get_columns("brokerage_notes")}
        stmts = []
        if "segment" not in cols:
            stmts.append("ALTER TABLE brokerage_notes ADD COLUMN segment VARCHAR(20) DEFAULT 'BOVESPA'")
        if "daytrade_gross" not in cols:
            stmts.append("ALTER TABLE brokerage_notes ADD COLUMN daytrade_gross NUMERIC(18,6) DEFAULT 0")
        if "normal_gross" not in cols:
            stmts.append("ALTER TABLE brokerage_notes ADD COLUMN normal_gross NUMERIC(18,6) DEFAULT 0")
        if stmts:
            with db.engine.begin() as conn:
                for s in stmts:
                    conn.execute(text(s))
    except Exception:  # noqa: BLE001
        # Não derruba a app, mas registra para diagnóstico (antes era silencioso).
        log.exception("Falha na migração leve de colunas BM&F.")


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Garante diretórios de instância/uploads
    os.makedirs(instance_dir, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # Extensões
    db.init_app(app)
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

    # Schema
    with app.app_context():
        db.create_all()
        _ensure_bmf_columns()

    return app
