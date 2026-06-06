"""Testes do recurso de IA do diário (sem chamar a API de verdade)."""
import base64

from app.extensions import db
from app.models import Note
from app.services import ai_insights


def _login(client, email="t@t.com", password="password"):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


def test_is_enabled(app):
    original = app.config.get("ANTHROPIC_API_KEY")
    try:
        app.config["ANTHROPIC_API_KEY"] = None
        assert ai_insights.is_enabled() is False
        app.config["ANTHROPIC_API_KEY"] = "sk-test"
        assert ai_insights.is_enabled() is True
    finally:
        app.config["ANTHROPIC_API_KEY"] = original


def test_analisar_desabilitado_sem_chave(app, client, user):
    app.config["ANTHROPIC_API_KEY"] = None
    _login(client)
    n = Note(user_id=user.id, body="<p>comprei PETR4 no rompimento</p>")
    db.session.add(n)
    db.session.commit()
    r = client.post(f"/diario/{n.id}/analisar")
    assert r.status_code == 200
    assert r.get_json()["ok"] is False


def test_analisar_mockado(client, user, monkeypatch):
    fake = {"ok": True, "analysis": {
        "resumo": "Operou no rompimento.", "pontos_fortes": ["seguiu o plano"],
        "alertas": ["sem stop definido"], "dica": "defina o stop antes de entrar"}}
    monkeypatch.setattr(ai_insights, "analyze_note",
                        lambda title, tags, asset, body, strategy=None, images=None: fake)
    _login(client)
    n = Note(user_id=user.id, title="PETR4", body="<p>tese</p>")
    db.session.add(n)
    db.session.commit()
    r = client.post(f"/diario/{n.id}/analisar")
    j = r.get_json()
    assert j["ok"] is True
    assert j["analysis"]["dica"] == "defina o stop antes de entrar"


def test_analisar_exige_login(client):
    r = client.post("/diario/1/analisar", follow_redirects=False)
    assert r.status_code in (302, 401)


# --------------------------------------------------------------------------- #
# Visão: a IA precisa receber as imagens anexadas no diário
# --------------------------------------------------------------------------- #
# JPEG válido pequeno (>200 bytes) só para o extrator aceitar
_IMG_B64 = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 600 + b"\xff\xd9").decode()


def test_images_from_html_extrai_data_uri():
    html = f'<p>print</p><img src="data:image/png;base64,{_IMG_B64}" alt="x">'
    imgs = ai_insights.images_from_html(html)
    assert len(imgs) == 1
    assert imgs[0]["type"] == "image"
    assert imgs[0]["source"]["media_type"] == "image/png"
    assert imgs[0]["source"]["data"] == _IMG_B64


def test_images_from_html_ignora_invalida_e_normaliza_jpg():
    assert ai_insights.images_from_html('<img src="data:image/png;base64,@@@">') == []
    jpg = f'<img src="data:image/jpg;base64,{_IMG_B64}">'
    assert ai_insights.images_from_html(jpg)[0]["source"]["media_type"] == "image/jpeg"


def test_rota_analisar_passa_imagens_do_corpo(client, user, monkeypatch):
    captured = {}

    def fake(title, tags, asset, body, strategy=None, images=None):
        captured["images"] = images
        return {"ok": True, "analysis": {"resumo": "", "pontos_fortes": [],
                                         "alertas": [], "dica": ""}}

    monkeypatch.setattr(ai_insights, "analyze_note", fake)
    _login(client)
    n = Note(user_id=user.id, title="PETR4",
             body=f'<p>setup</p><img src="data:image/png;base64,{_IMG_B64}">')
    db.session.add(n)
    db.session.commit()
    r = client.post(f"/diario/{n.id}/analisar")
    assert r.get_json()["ok"] is True
    assert captured["images"] and captured["images"][0]["type"] == "image"
