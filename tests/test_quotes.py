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


def test_brapi_usado_quando_ha_token(monkeypatch):
    """Com BRAPI_TOKEN, a brapi é consultada em lote; Yahoo não é chamado."""
    quotes._CACHE.clear()
    monkeypatch.setattr(quotes, "_brapi_token", lambda: "tok")
    monkeypatch.setattr(quotes, "_fetch_brapi",
                        lambda ts, tok: {t: 42.0 for t in ts})
    monkeypatch.setattr(quotes, "_safe_fetch",
                        lambda t: (_ for _ in ()).throw(AssertionError("não usar Yahoo")))
    r = quotes.get_prices(["PETR4", "VALE3"])
    assert r == {"PETR4": 42.0, "VALE3": 42.0}


def test_fallback_yahoo_quando_brapi_falha(monkeypatch):
    quotes._CACHE.clear()
    monkeypatch.setattr(quotes, "_brapi_token", lambda: "tok")

    def boom(ts, tok):
        raise RuntimeError("brapi fora do ar")

    monkeypatch.setattr(quotes, "_fetch_brapi", boom)
    monkeypatch.setattr(quotes, "_safe_fetch", lambda t: 7.0)
    r = quotes.get_prices(["PETR4"])
    assert r == {"PETR4": 7.0}
