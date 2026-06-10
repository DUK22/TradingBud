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


def test_login_next_externo_e_bloqueado(client):
    """?next= externo (open redirect) é ignorado — vai para o dashboard."""
    _make_user("n@n.com")
    for evil in ("https://evil.com/", "//evil.com/x", "http://evil.com"):
        client.get("/logout", follow_redirects=True)
        resp = client.post(f"/login?next={evil}",
                           data={"email": "n@n.com", "password": "password"},
                           follow_redirects=False)
        assert resp.status_code == 302
        assert "evil.com" not in resp.headers["Location"]


def test_login_next_interno_funciona(client):
    _make_user("m@m.com")
    resp = client.post("/login?next=/apuracao",
                       data={"email": "m@m.com", "password": "password"},
                       follow_redirects=False)
    assert resp.headers["Location"].endswith("/apuracao")


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


def test_fluxo_reset_de_senha(client, app):
    """Pede reset, usa o token e entra com a senha nova."""
    from app.services import tokens
    u = _make_user("reset@x.com", "senhaantiga")

    # Pedido não revela existência de conta (mensagem neutra, 302 p/ login)
    r = client.post("/esqueci-senha", data={"email": "reset@x.com"},
                    follow_redirects=False)
    assert r.status_code == 302

    token = tokens.generate(u.id, tokens.SALT_RESET)
    r = client.post(f"/redefinir-senha/{token}",
                    data={"password": "senhanova123", "confirm": "senhanova123"},
                    follow_redirects=False)
    assert r.status_code == 302

    ok = _login(client, "reset@x.com", "senhanova123")
    assert ok.status_code == 200
    client.get("/logout", follow_redirects=True)
    fail = client.post("/login", data={"email": "reset@x.com",
                                       "password": "senhaantiga"},
                       follow_redirects=True)
    assert b"inv" in fail.data.lower()


def test_token_de_reset_invalido_e_rejeitado(client):
    r = client.get("/redefinir-senha/token-invalido", follow_redirects=False)
    assert r.status_code == 302
    assert "/esqueci-senha" in r.headers["Location"]


def test_verificacao_de_email(client):
    from app.models import User
    from app.services import tokens
    u = _make_user("verif@x.com")
    assert u.email_verified is False
    token = tokens.generate(u.id, tokens.SALT_VERIFY)
    r = client.get(f"/verificar-email/{token}", follow_redirects=False)
    assert r.status_code == 302
    assert db.session.get(User, u.id).email_verified is True


def test_token_de_verificacao_nao_serve_para_reset(client):
    """Salts distintos: token de verificação não redefine senha."""
    from app.services import tokens
    u = _make_user("cross@x.com")
    token = tokens.generate(u.id, tokens.SALT_VERIFY)
    r = client.post(f"/redefinir-senha/{token}",
                    data={"password": "senhanova123", "confirm": "senhanova123"},
                    follow_redirects=False)
    assert "/esqueci-senha" in r.headers["Location"]
