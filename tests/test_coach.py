"""Testes do Coach (estratégias nomeadas + checklist/chat/resumo/print com IA mockada)."""
import io

from app.extensions import db
from app.models import StrategyProfile, User
from app.services import ai_insights


def _login(client, email="t@t.com", password="password"):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


def _png_bytes():
    # PNG mínimo válido (1x1) só para subir como upload
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000154a24f9d0000000049454e44ae426082")


def test_salvar_estrategia(client, user):
    _login(client)
    r = client.post("/coach/estrategia",
                    data={"name": "Win rompimento", "content": "Rompimento de WINFUT, stop 150 pts"},
                    follow_redirects=True)
    assert r.status_code == 200
    sp = StrategyProfile.query.filter_by(user_id=user.id).first()
    assert sp and "WINFUT" in sp.content and sp.name == "Win rompimento"
    db.session.expire(user)
    assert db.session.get(User, user.id).active_strategy_id == sp.id


def test_selecionar_estrategia(client, user):
    _login(client)
    a = StrategyProfile(user_id=user.id, name="A", content="estrategia A")
    b = StrategyProfile(user_id=user.id, name="B", content="estrategia B")
    db.session.add_all([a, b])
    db.session.commit()
    client.post(f"/coach/estrategia/{b.id}/selecionar", follow_redirects=True)
    db.session.expire(user)
    assert db.session.get(User, user.id).active_strategy_id == b.id


def test_excluir_estrategia_reaponta_ativa(client, user):
    _login(client)
    a = StrategyProfile(user_id=user.id, name="A", content="x")
    b = StrategyProfile(user_id=user.id, name="B", content="y")
    db.session.add_all([a, b])
    db.session.commit()
    user.active_strategy_id = a.id
    db.session.commit()
    client.post(f"/coach/estrategia/{a.id}/excluir", follow_redirects=True)
    db.session.expire(user)
    assert db.session.get(StrategyProfile, a.id) is None
    assert db.session.get(User, user.id).active_strategy_id == b.id


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


def test_coach_analisar_print_mockado(client, user, monkeypatch):
    captured = {}

    def fake(strategy, images, context=""):
        captured["n"] = len(images)
        return {"ok": True, "analysis": {"resumo": "Gráfico de WIN em 5min.",
                "pontos_fortes": [], "alertas": ["sem stop visível"], "dica": "marque o stop"}}

    monkeypatch.setattr(ai_insights, "analyze_screenshot", fake)
    _login(client)
    data = {"imagem": (io.BytesIO(_png_bytes()), "tela.png"), "contexto": "vou comprar"}
    r = client.post("/coach/analisar-imagem", data=data, content_type="multipart/form-data")
    j = r.get_json()
    assert j["ok"] and captured["n"] == 1
    assert "stop" in j["analysis"]["dica"]


def test_coach_analisar_print_sem_imagem(client, user):
    _login(client)
    r = client.post("/coach/analisar-imagem", data={}, content_type="multipart/form-data")
    assert r.get_json()["ok"] is False


def test_coach_exige_login(client):
    assert client.post("/coach/chat", json={}, follow_redirects=False).status_code in (302, 401)
