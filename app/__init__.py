"""Application factory.

Cria a app Flask, inicializa extensões (SQLAlchemy, Login), registra os
blueprints (auth e main) e garante a criação do schema SQLite.
"""
import os
from flask import Flask

from config import Config, instance_dir
from .extensions import db, login_manager
from .utils import register_filters


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
    except Exception:
        pass


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Garante diretórios de instância/uploads
    os.makedirs(instance_dir, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # Extensões
    db.init_app(app)
    login_manager.init_app(app)

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

    # Schema
    with app.app_context():
        db.create_all()
        _ensure_bmf_columns()

    return app
