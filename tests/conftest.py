"""Fixtures compartilhadas dos testes (pytest).

Cada teste roda dentro de um app context com um banco SQLite em memória
recriado do zero (isolamento total entre testes).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db as _db  # noqa: E402
from app.models import User  # noqa: E402
from config import TestConfig  # noqa: E402


@pytest.fixture(scope="session")
def app():
    application = create_app(TestConfig)
    yield application


@pytest.fixture(autouse=True)
def _fresh_db(app):
    """Recria o schema antes de cada teste e abre um app context."""
    with app.app_context():
        _db.drop_all()
        _db.create_all()
        yield
        _db.session.remove()


@pytest.fixture
def db():
    return _db


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def user():
    """Usuário de teste já persistido (senha: 'password')."""
    u = User(name="Teste", email="t@t.com")
    u.set_password("password")
    _db.session.add(u)
    _db.session.commit()
    return u
