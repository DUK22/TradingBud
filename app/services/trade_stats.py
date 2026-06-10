"""Estatísticas de performance calculadas dos negócios REAIS do usuário.

Cada "operação fechada" = um day trade (por ativo/dia) ou uma venda de swing.
Tudo derivado do ApuracaoResult do tax_engine — nenhuma chamada de IA aqui.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

D0 = Decimal("0")

WEEKDAYS_PT = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def _closed_ops(result) -> list:
    """[(date, asset, resultado, 'DAY'|'SWING'), ...] ordenado por data."""
    ops = [(r.trade_date, r.asset, r.net_result, "DAY") for r in result.day_results]
    ops += [(s.trade_date, s.asset, s.result, "SWING") for s in result.swing_sales]
    ops.sort(key=lambda o: o[0])
    return ops


def compute_stats(result) -> dict:
    """Resumo geral + quebras por ativo e por dia da semana."""
    ops = _closed_ops(result)
    res = [o[2] for o in ops]
    wins = [x for x in res if x > 0]
    losses = [x for x in res if x < 0]
    gross_profit = sum(wins, D0)
    gross_loss = -sum(losses, D0)          # positivo
    n = len(res)

    overall = {
        "n_ops": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (Decimal(len(wins)) / n * 100) if n else D0,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else None,
        "avg_win": (gross_profit / len(wins)) if wins else D0,
        "avg_loss": (gross_loss / len(losses)) if losses else D0,
        "expectancy": (sum(res, D0) / n) if n else D0,
        "best": max(res) if res else D0,
        "worst": min(res) if res else D0,
        "net": sum(res, D0),
    }

    def bucket(keyfn):
        agg = defaultdict(lambda: {"n": 0, "wins": 0, "net": D0})
        for op in ops:
            b = agg[keyfn(op)]
            b["n"] += 1
            b["wins"] += 1 if op[2] > 0 else 0
            b["net"] += op[2]
        out = []
        for k, b in agg.items():
            b["key"] = k
            b["win_rate"] = Decimal(b["wins"]) / b["n"] * 100 if b["n"] else D0
            out.append(b)
        return out

    by_asset = sorted(bucket(lambda o: o[1]), key=lambda b: abs(b["net"]), reverse=True)[:8]
    by_weekday = bucket(lambda o: o[0].weekday())
    by_weekday.sort(key=lambda b: b["key"])
    for b in by_weekday:
        b["label"] = WEEKDAYS_PT[b["key"]]

    by_kind = bucket(lambda o: o[3])
    by_kind.sort(key=lambda b: b["key"])

    return {"overall": overall, "by_asset": by_asset,
            "by_weekday": by_weekday, "by_kind": by_kind}
