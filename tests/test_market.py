"""Testes da página Mercado (layout fixo, símbolos e posição)."""
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import BrokerageNote, Trade


def _login(client, email="t@t.com", password="password"):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


def test_mercado_renderiza_widgets_fixos(client, user):
    _login(client)
    h = client.get("/mercado").get_data(as_text=True)
    for piece in ("tv-chart", "tv-tech", "tv-calendar", "tv-news",
                  "Calculadoras do trader", "BMFBOVESPA:PETR4"):
        assert piece in h


def test_mercado_resolve_ticker_americano(client, user):
    _login(client)
    h = client.get("/mercado?symbol=EWZ").get_data(as_text=True)
    assert "AMEX:EWZ" in h


def test_mercado_mostra_posicao_do_ativo(client, user):
    n = BrokerageNote(user_id=user.id, broker="T", trade_date=date(2026, 5, 5),
                      source="MANUAL")
    db.session.add(n)
    db.session.flush()
    db.session.add(Trade(user_id=user.id, note_id=n.id, trade_date=n.trade_date,
                         asset="PETR4", market="VISTA", side="C",
                         quantity=Decimal("100"), price=Decimal("38"),
                         gross_value=Decimal("3800")))
    db.session.commit()
    _login(client)
    h = client.get("/mercado?symbol=BMFBOVESPA:PETR4").get_data(as_text=True)
    assert "Sua posição em PETR4" in h
    assert "pos-panel" in h


def test_mercado_exige_login(client):
    r = client.get("/mercado", follow_redirects=False)
    assert r.status_code == 302
