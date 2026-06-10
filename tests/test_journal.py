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


def test_imagem_base64_vira_arquivo_e_rota_autenticada(client, user, app):
    """Ao salvar, a imagem base64 sai do banco e vira arquivo + rota privada."""
    import base64 as b64
    import re

    from app.models import Note

    client.post("/login", data={"email": "t@t.com", "password": "password"})
    r = client.get("/diario/novo", follow_redirects=False)
    note_id = int(r.headers["Location"].rstrip("/").rsplit("/", 1)[-1])

    # PNG 1x1 válido
    png = b64.b64encode(bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d4944415478da63fcffff3f030005fe02fea7568a2d"
        "0000000049454e44ae426082")).decode()
    body = f'<p>antes</p><img src="data:image/png;base64,{png}"><p>depois</p>'
    r = client.post(f"/diario/{note_id}",
                    json={"title": "t", "body": body, "tags": "", "asset": ""})
    assert r.status_code == 200

    from app.extensions import db
    note = db.session.get(Note, note_id)
    assert "base64" not in note.body            # blob saiu do banco
    m = re.search(r'src="([^"]*/diario/img/[^"]+)"', note.body)
    assert m, note.body

    img = client.get(m.group(1))
    assert img.status_code == 200
    assert img.data.startswith(b"\x89PNG")

    # outro usuário não enxerga a mesma imagem (diretório por usuário)
    from app.models import User
    u2 = User(name="Z", email="z@z.com")
    u2.set_password("password")
    db.session.add(u2)
    db.session.commit()
    client.get("/logout", follow_redirects=True)
    client.post("/login", data={"email": "z@z.com", "password": "password"})
    img2 = client.get(m.group(1))
    assert img2.status_code == 404
