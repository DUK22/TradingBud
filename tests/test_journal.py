"""Testes do diário de trades (criar, autosave/sanitização, busca, excluir, isolamento)."""
from app.extensions import db
from app.models import Note, User


def _login(client, email="t@t.com", password="password"):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


def test_nova_anotacao_cria(client, user):
    _login(client)
    r = client.get("/diario/novo", follow_redirects=False)
    assert r.status_code == 302
    assert Note.query.filter_by(user_id=user.id).count() == 1


def test_autosave_sanitiza_e_normaliza(client, user):
    _login(client)
    note = Note(user_id=user.id)
    db.session.add(note)
    db.session.commit()
    r = client.post(f"/diario/{note.id}", json={
        "title": "Minha tese", "asset": "petr4", "tags": "setup, setup, erro",
        "body": "<p>ok</p><script>alert(1)</script>",
    })
    assert r.status_code == 200
    db.session.expire(note)
    n = db.session.get(Note, note.id)
    assert "<script>" not in n.body and "<p>ok</p>" in n.body   # sanitizado
    assert n.asset == "PETR4"                                   # normalizado
    assert n.tag_list == ["setup", "erro"]                      # sem duplicata


def test_busca(client, user):
    _login(client)
    db.session.add(Note(user_id=user.id, title="PETR4 rompimento", body="<p>tese</p>", asset="PETR4"))
    db.session.commit()
    h = client.get("/diario?q=rompimento").get_data(as_text=True)
    assert "PETR4 rompimento" in h


def test_excluir(client, user):
    _login(client)
    n = Note(user_id=user.id, title="x")
    db.session.add(n)
    db.session.commit()
    nid = n.id
    assert client.post(f"/diario/{nid}/excluir").status_code == 302
    assert db.session.get(Note, nid) is None


def test_isolamento_entre_usuarios(client, user):
    outro = User(name="o", email="o@o.com")
    outro.set_password("password")
    db.session.add(outro)
    db.session.commit()
    n = Note(user_id=outro.id, title="secreta")
    db.session.add(n)
    db.session.commit()
    _login(client)   # entra como t@t.com (user)
    assert client.get(f"/diario/{n.id}").status_code == 404
