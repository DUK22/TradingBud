"""Testes do PWA (manifest, service worker e página offline) — rotas públicas."""


def test_manifest(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert "manifest" in r.mimetype           # application/manifest+json
    assert b"TradingBud" in r.data
    assert b"icon-512.png" in r.data


def test_service_worker(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.mimetype
    assert r.headers.get("Service-Worker-Allowed") == "/"
    assert "addEventListener('fetch'" in r.get_data(as_text=True)


def test_offline_page(client):
    r = client.get("/offline")
    assert r.status_code == 200
    assert "offline" in r.get_data(as_text=True).lower()
