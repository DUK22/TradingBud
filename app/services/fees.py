"""Estimativa de custos operacionais (nota provisória).

A B3 não informa as taxas antes da nota oficial, então estimamos os custos como
uma fração do volume financeiro (configurável em B3_COST_RATE). É uma APROXIMAÇÃO
para o trader ter uma ideia do líquido/IR no mesmo dia; a nota oficial substitui.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from flask import current_app


def estimate_costs(volume) -> Decimal:
    """Custo estimado a partir do volume financeiro total (R$)."""
    rate = Decimal(str(current_app.config.get("B3_COST_RATE", "0.0003")))
    vol = Decimal(str(volume or 0))
    return (vol * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
