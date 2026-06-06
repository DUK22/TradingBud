"""Testes do layout salvo na conta (página Mercado)."""
import json

from app.extensions import db
from app.models import User


def _login(client, email="t@t.com", password="password"):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


def test_salva_layout_na_conta(client, user):
    _login(client)
    layout = [{"id": "chart", "type": "chart", "x": 0, "y": 0, "w": 8, "h": 8}]
    r = client.post("/mercado/layout", json=layout)
    assert r.status_code == 200 and r.get_json()["ok"] is True
    db.session.expire(user)
    saved = json.loads(db.session.get(User, user.id).layout_mercado)
    assert saved[0]["type"] == "chart" and saved[0]["w"] == 8


def test_layout_invalido_400(client, user):
    _login(client)
    r = client.post("/mercado/layout", json={"nao": "e lista"})
    assert r.status_code == 400


def test_mercado_carrega_layout_salvo(client, user):
    user.layout_mercado = json.dumps([{"id": "news", "type": "news", "x": 0, "y": 0, "w": 6, "h": 6}])
    db.session.commit()
    _login(client)
    h = client.get("/mercado").get_data(as_text=True)
    assert '"type": "news"' in h        # injetado em const SAVED


def test_layout_exige_login(client):
    r = client.post("/mercado/layout", json=[], follow_redirects=False)
    assert r.status_code in (302, 401)
