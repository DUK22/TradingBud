"""Relatório anual para a DIRPF (declaração de ajuste).

Consolida, para um ano-calendário:
  - Bens e Direitos: posições em 31/12 com preço médio e custo total, já com o
    texto de "Discriminação" pronto e o grupo/código sugerido por classe.
  - Renda Variável: bases, imposto, IRRF e DARF mês a mês (operações comuns +
    day trade + FII) — os valores que se digitam ficha a ficha.
  - Rendimentos isentos: lucros de vendas de ações à vista até R$20k/mês.
  - Prejuízos a compensar em 31/12 (para transportar ao ano seguinte).

IMPORTANTE: apoio ao preenchimento; confira grupo/código no programa da
Receita e valide com seu contador.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from . import asset_classes, tax_engine

D0 = Decimal("0")

# Grupo/código SUGERIDOS para Bens e Direitos (DIRPF 2024+). Conferir no programa.
GROUP_CODE = {
    asset_classes.ACAO: ("03", "01", "Ações (inclusive listadas em bolsa)"),
    asset_classes.BDR: ("04", "04", "Ativos negociados no exterior via BDR"),
    asset_classes.FII: ("07", "03", "Fundos de Investimento Imobiliário (FII)"),
    asset_classes.ETF: ("07", "09", "Demais fundos (ETF de renda variável)"),
    asset_classes.ETF_RF: ("07", "09", "Demais fundos (ETF de renda fixa)"),
}


def build(notes, adjustments, year: int, incomes=()) -> dict:
    """Calcula o relatório do ano usando só o histórico até 31/12/year."""
    cutoff = date(year, 12, 31)
    notes_y = [n for n in notes if n.trade_date <= cutoff]
    adj_y = [a for a in (adjustments or []) if a.event_date <= cutoff]
    result = tax_engine.compute(notes_y, adjustments=adj_y)

    months = [m for m in result.months if m.year == year]
    prev = [m for m in result.months if m.year < year]
    prev_last = prev[-1] if prev else None

    # Posições em 31/12 com texto de discriminação pronto
    bens = []
    for p in result.positions:
        klass = asset_classes.classify(p.asset)
        grupo, codigo, rotulo = GROUP_CODE.get(klass, ("03", "01", "Ações"))
        unidade = "cota(s)" if klass in (asset_classes.FII, asset_classes.ETF,
                                         asset_classes.ETF_RF) else "ação(ões)"
        if p.market == "FUTURO":
            continue   # futuros não são "bens" — posição é diária (ajuste)
        discr = (f"{p.qty:.0f} {unidade} de {p.asset}, custo médio de "
                 f"R$ {p.avg_price:.2f}, custo total de R$ {p.total_cost:.2f}, "
                 f"conforme notas de corretagem.")
        bens.append({
            "asset": p.asset, "classe": klass, "grupo": grupo, "codigo": codigo,
            "rotulo": rotulo, "qty": p.qty, "avg_price": p.avg_price,
            "total_cost": p.total_cost, "discriminacao": discr,
        })

    isentos_20k = sum((m.exempt_result for m in months if m.exempt_result > 0), D0)
    total_darf = sum((m.darf for m in months), D0)
    total_tax = sum((m.total_tax for m in months), D0)
    total_irrf = sum((m.irrf_day + m.irrf_swing for m in months), D0)

    # Proventos do ano (dividendos isentos, JCP exclusiva, rendimentos FII)
    incomes_y = [i for i in (incomes or []) if i.income_date.year == year]
    prov_totals = {"DIVIDENDO": D0, "JCP": D0, "RENDIMENTO": D0}
    prov_by_asset: dict = {}
    for i in incomes_y:
        v = Decimal(str(i.value))
        prov_totals[i.kind] = prov_totals.get(i.kind, D0) + v
        bucket = prov_by_asset.setdefault(i.asset, {"DIVIDENDO": D0, "JCP": D0,
                                                    "RENDIMENTO": D0, "TOTAL": D0})
        bucket[i.kind] = bucket.get(i.kind, D0) + v
        bucket["TOTAL"] += v
    prov_assets = sorted(prov_by_asset.items(), key=lambda kv: kv[1]["TOTAL"],
                         reverse=True)

    last = months[-1] if months else prev_last
    losses = {
        "day": last.day_loss_acc if last else D0,
        "swing": last.swing_loss_acc if last else D0,
        "fii": last.fii_loss_acc if last else D0,
    }
    losses_prev = {
        "day": prev_last.day_loss_acc if prev_last else D0,
        "swing": prev_last.swing_loss_acc if prev_last else D0,
        "fii": prev_last.fii_loss_acc if prev_last else D0,
    }

    return {
        "year": year,
        "months": months,
        "bens": bens,
        "isentos_20k": isentos_20k,
        "total_darf": total_darf,
        "total_tax": total_tax,
        "total_irrf": total_irrf,
        "losses": losses,
        "losses_prev": losses_prev,
        "prov_totals": prov_totals,
        "prov_assets": prov_assets,
        "prov_total": sum(prov_totals.values(), D0),
        "warnings": result.warnings,
        "n_notes": len(notes_y),
        "has_data": bool(months or bens),
        "darf_codigo": tax_engine.DARF_CODIGO,
    }


def years_available(notes) -> list[int]:
    return sorted({n.trade_date.year for n in notes}, reverse=True)
