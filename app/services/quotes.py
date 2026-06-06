"""Cotações ao vivo de ações da B3 (Yahoo Finance, sem chave).

Fonte não-oficial, usada só para exibir preço/variação na carteira — não é dado
de pregão garantido. Tem cache curto e timeout, e degrada para None em falha.
Futuros (WIN/WDO...) não são cobertos aqui (o Yahoo não os expõe de forma simples).
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, float]] = {}   # ticker -> (preço, timestamp)
_TTL = 60                                      # segundos
_TIMEOUT = 4
_UA = "Mozilla/5.0 (compatible; IRTraders/1.0)"


def _fetch_one(ticker: str):
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
    """Retorna {ticker: preço|None} para ações da B3."""
    tickers = [str(t).upper().strip() for t in tickers if str(t).strip()]
    now = time.time()
    result, to_fetch = {}, []
    for t in tickers:
        cached = _CACHE.get(t)
        if cached and now - cached[1] < _TTL:
            result[t] = cached[0]
        else:
            to_fetch.append(t)
    if to_fetch:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for t, price in zip(to_fetch, ex.map(_safe_fetch, to_fetch), strict=False):
                if price is not None:
                    _CACHE[t] = (price, now)
                result[t] = price
    return result
