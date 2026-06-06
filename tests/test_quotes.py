"""Testes do serviço de cotações e da rota /api/cotacoes (sem acesso à rede)."""
from app.services import quotes


def _login(client, email="t@t.com", password="password"):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


def test_get_prices_vazio():
    assert quotes.get_prices([]) == {}


def test_get_prices_usa_cache(monkeypatch):
    calls = []

    def fake(ticker):
        calls.append(ticker)
        return 10.0

    monkeypatch.setattr(quotes, "_safe_fetch", fake)
    quotes._CACHE.clear()
    r1 = quotes.get_prices(["PETR4"])
    r2 = quotes.get_prices(["PETR4"])      # deve vir do cache
    assert r1["PETR4"] == 10.0 and r2["PETR4"] == 10.0
    assert calls == ["PETR4"]              # buscou só uma vez


def test_api_cotacoes(client, user, monkeypatch):
    monkeypatch.setattr(quotes, "get_prices", lambda ts: {t: 5.0 for t in ts})
    _login(client)
    r = client.get("/api/cotacoes?tickers=PETR4,VALE3")
    assert r.status_code == 200
    assert r.get_json() == {"PETR4": 5.0, "VALE3": 5.0}


def test_api_cotacoes_exige_login(client):
    r = client.get("/api/cotacoes?tickers=PETR4", follow_redirects=False)
    assert r.status_code == 302   # redireciona para login
