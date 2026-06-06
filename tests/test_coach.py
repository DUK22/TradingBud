"""Testes do Coach (estratégia + checklist/chat/resumo com IA mockada)."""
from app.extensions import db
from app.models import User
from app.services import ai_insights


def _login(client, email="t@t.com", password="password"):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


def test_salvar_estrategia(client, user):
    _login(client)
    r = client.post("/coach/estrategia", data={"strategy": "Rompimento de WINFUT, stop 150 pts"},
                    follow_redirects=True)
    assert r.status_code == 200
    db.session.expire(user)
    assert "WINFUT" in db.session.get(User, user.id).strategy


def test_coach_checklist_mockado(client, user, monkeypatch):
    monkeypatch.setattr(ai_insights, "pre_trade_checklist",
                        lambda strategy, plan: {"ok": True, "analysis": {
                            "itens": [{"criterio": "Stop", "atende": True, "comentario": "ok"}],
                            "veredito": "Plano coerente."}})
    _login(client)
    r = client.post("/coach/checklist", json={"plan": "comprar win 130000"})
    j = r.get_json()
    assert j["ok"] and j["analysis"]["veredito"] == "Plano coerente."


def test_coach_chat_mockado(client, user, monkeypatch):
    monkeypatch.setattr(ai_insights, "chat",
                        lambda strategy, notes, q: {"ok": True, "text": "Você erra mais às quintas."})
    _login(client)
    r = client.post("/coach/chat", json={"question": "onde erro mais?"})
    assert r.get_json()["text"].startswith("Você erra")


def test_coach_exige_login(client):
    assert client.post("/coach/chat", json={}, follow_redirects=False).status_code in (302, 401)
