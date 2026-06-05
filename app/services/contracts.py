"""Especificações de contratos futuros da B3 (valor do ponto) e cálculo do
valor financeiro de um contrato.

valor financeiro (notional) = preço_em_pontos × valor_do_ponto × quantidade

Ex.: WIN a 130.000 pontos, 1 contrato → 130000 × 0,20 = R$ 26.000,00.
"""
from __future__ import annotations

import re
from decimal import Decimal

# R$ por ponto, por contrato (os mais negociados; outros retornam None).
POINT_VALUES = {
    "WIN": Decimal("0.20"),   # mini índice
    "IND": Decimal("1.00"),   # índice cheio
    "WDO": Decimal("10.00"),  # mini dólar
    "DOL": Decimal("50.00"),  # dólar cheio
}

CONTRACT_NAMES = {
    "WIN": "Mini Índice", "IND": "Índice", "WDO": "Mini Dólar", "DOL": "Dólar",
}

# Ticker de futuro: raiz (letras) + mês (F G H J K M N Q U V X Z) + ano (2 díg).
_ROOT_RE = re.compile(r"^([A-Z]+?)[FGHJKMNQUVXZ]\d{2}$")


def contract_root(ticker: str | None) -> str | None:
    if not ticker:
        return None
    m = _ROOT_RE.match(ticker.upper().strip())
    return m.group(1) if m else None


def point_value(ticker: str | None) -> Decimal | None:
    root = contract_root(ticker)
    return POINT_VALUES.get(root) if root else None


def contract_name(ticker: str | None) -> str | None:
    root = contract_root(ticker)
    return CONTRACT_NAMES.get(root) if root else None


def contract_value(ticker, price, quantity) -> Decimal | None:
    """Valor financeiro (notional) do contrato, ou None se a raiz é desconhecida."""
    pv = point_value(ticker)
    if pv is None:
        return None
    return Decimal(str(price)) * pv * Decimal(str(quantity))
