"""Cotações ao vivo de ações/FIIs/ETFs da B3.

Provedores (em ordem):
  1. brapi.dev — fonte dedicada à B3; usada quando BRAPI_TOKEN está configurado
     (plano gratuito disponível em https://brapi.dev). Busca em lote.
  2. Yahoo Finance (não-oficial, sem chave) — fallback, ou padrão sem token.

Uso apenas para exibir preço/variação na carteira — não é dado de pregão
garantido. Cache curto, timeout agressivo e degradação para None em falha.
Futuros (WIN/WDO...) não são cobertos.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, float]] = {}   # ticker -> (preço, timestamp)
_TTL = 60                                      # segundos
_TIMEOUT = 4
_UA = "Mozilla/5.0 (compatible; IRTraders/1.0)"
_BRAPI_BATCH = 20                              # tickers por chamada


def _brapi_token() -> str | None:
    try:
        from flask import current_app
        token = current_app.config.get("BRAPI_TOKEN")
        if token:
            return token
    except (ImportError, RuntimeError):
        pass
    return os.environ.get("BRAPI_TOKEN") or None


def _fetch_brapi(tickers: list[str], token: str) -> dict[str, float]:
    """Busca um lote de cotações na brapi. Retorna só o que veio com preço."""
    out: dict[str, float] = {}
    for i in range(0, len(tickers), _BRAPI_BATCH):
        chunk = tickers[i:i + _BRAPI_BATCH]
        url = ("https://brapi.dev/api/quote/"
               + urllib.parse.quote(",".join(chunk))
               + "?token=" + urllib.parse.quote(token))
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            data = json.load(resp)
        for item in data.get("results", []):
            price = item.get("regularMarketPrice")
            symbol = (item.get("symbol") or "").upper()
            if symbol and price is not None:
                out[symbol] = float(price)
    return out


def _fetch_one(ticker: str):
    """Fallback: Yahoo Finance (1 ticker por chamada, sufixo .SA)."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{ticker}.SA?interval=1d&range=1d")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
        data = json.load(resp)
    return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])


def _safe_fetch(ticker: str):
    try:
        return _fetch_one(ticker)
    except Exception:  # noqa: BLE001
        log.info("Cotação indisponível para %s", ticker)
        return None


def get_prices(tickers) -> dict:
    """Retorna {ticker: preço|None} para ativos da B3."""
    tickers = [str(t).upper().strip() for t in tickers if str(t).strip()]
    now = time.time()
    result, to_fetch = {}, []
    for t in tickers:
        cached = _CACHE.get(t)
        if cached and now - cached[1] < _TTL:
            result[t] = cached[0]
        else:
            to_fetch.append(t)
    if not to_fetch:
        return result

    # 1) brapi em lote (quando há token configurado)
    token = _brapi_token()
    if token:
        try:
            found = _fetch_brapi(to_fetch, token)
        except Exception:  # noqa: BLE001
            log.warning("brapi indisponível; caindo para o fallback (Yahoo).")
            found = {}
        for t, price in found.items():
            _CACHE[t] = (price, now)
            result[t] = price
        to_fetch = [t for t in to_fetch if t not in found]

    # 2) Yahoo (fallback / padrão sem token)
    if to_fetch:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for t, price in zip(to_fetch, ex.map(_safe_fetch, to_fetch), strict=False):
                if price is not None:
                    _CACHE[t] = (price, now)
                result[t] = price
    return result
