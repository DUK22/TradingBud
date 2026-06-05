"""Testes de criptografia do CPF e rotas LGPD (exportar/excluir conta)."""
from datetime import date

from sqlalchemy import text

from app.extensions import db
from app.models import BrokerageNote, User


def _login(client, email="t@t.com", password="password"):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


def test_trocar_senha(client, user):
    _login(client)
    r = client.post("/conta/senha", data={
        "atual": "password", "nova": "novasenha123", "confirma": "novasenha123",
    }, follow_redirects=True)
    assert r.status_code == 200
    db.session.expire(user)
    assert db.session.get(User, user.id).check_password("novasenha123")


def test_trocar_senha_atual_errada(client, user):
    _login(client)
    client.post("/conta/senha", data={
        "atual": "errada", "nova": "novasenha123", "confirma": "novasenha123",
    }, follow_redirects=True)
    db.session.expire(user)
    assert db.session.get(User, user.id).check_password("password")  # não mudou


def test_carregar_dados_de_exemplo(client, user):
    _login(client)
    r = client.post("/conta/exemplo", follow_redirects=False)
    assert r.status_code == 302
    assert BrokerageNote.query.filter_by(user_id=user.id).count() > 0


def test_cpf_criptografado_em_repouso(app):
    u = User(name="X", email="c@c.com", cpf="123.456.789-00")
    u.set_password("password")
    db.session.add(u)
    db.session.commit()

    raw = db.session.execute(
        text("SELECT cpf FROM users WHERE id = :i"), {"i": u.id}).scalar()
    assert raw is not None
    assert "123.456" not in raw          # não está em texto puro
    assert raw.startswith("gAAAA")       # token Fernet

    db.session.expire(u)                 # força releitura do banco
    assert db.session.get(User, u.id).cpf == "123.456.789-00"  # volta em claro


def test_exportar_dados(client, user):
    db.session.add(BrokerageNote(user_id=user.id, broker="T",
                                 trade_date=date(2026, 1, 1), source="MANUAL"))
    db.session.commit()
    _login(client)

    r = client.get("/conta/exportar")
    assert r.status_code == 200
    assert r.mimetype == "application/json"
    assert "attachment" in r.headers["Content-Disposition"]
    body = r.get_data(as_text=True)
    assert "t@t.com" in body
    assert '"notas"' in body


def test_excluir_conta_remove_tudo(client, user):
    uid = user.id
    db.session.add(BrokerageNote(user_id=uid, broker="T",
                                 trade_date=date(2026, 1, 1), source="MANUAL"))
    db.session.commit()
    _login(client)

    r = client.post("/conta/excluir", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]
    assert db.session.get(User, uid) is None
    # cascade removeu as notas do usuário
    assert BrokerageNote.query.filter_by(user_id=uid).count() == 0
