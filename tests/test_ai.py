"""Testes do recurso de IA do diário (sem chamar a API de verdade)."""
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
                        lambda title, tags, asset, body, strategy=None: fake)
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
