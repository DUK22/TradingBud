"""Testes de autenticação e isolamento de dados entre usuários."""
from datetime import date

from app.extensions import db
from app.models import BrokerageNote, User


def _make_user(email, password="password"):
    u = User(name="X", email=email)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return u


def _login(client, email, password="password"):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


def test_register_cria_usuario_e_loga(client):
    resp = client.post("/register", data={
        "name": "Maria", "email": "Maria@Ex.com", "cpf": "",
        "password": "senha12345", "confirm": "senha12345",
    }, follow_redirects=True)
    assert resp.status_code == 200
    u = User.query.filter_by(email="maria@ex.com").first()  # email normalizado
    assert u is not None


def test_login_senha_errada_falha(client):
    _make_user("a@a.com")
    resp = _login(client, "a@a.com", "errada")
    assert b"inv" in resp.data.lower()  # "inválidos"


def test_login_e_logout(client):
    _make_user("b@b.com")
    resp = _login(client, "b@b.com")
    assert resp.status_code == 200
    out = client.get("/logout", follow_redirects=True)
    assert out.status_code == 200


def test_rota_protegida_exige_login(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_isolamento_entre_usuarios(client):
    """Usuário não pode ver nota de outro (404, não 403 que vazaria existência)."""
    dono = _make_user("dono@x.com")
    _make_user("intruso@x.com")
    nota = BrokerageNote(user_id=dono.id, broker="T", trade_date=date(2026, 1, 1),
                         source="MANUAL")
    db.session.add(nota)
    db.session.commit()
    nota_id = nota.id

    _login(client, "intruso@x.com")
    resp = client.get(f"/notas/{nota_id}")
    assert resp.status_code == 404
