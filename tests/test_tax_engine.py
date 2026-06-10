"""Testes do engine de impostos (pytest).

    pytest -q
"""
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import BrokerageNote, Trade
from app.services import tax_engine


def _add(u, d, trades, irrf_day=0, irrf_swing=0):
    note = BrokerageNote(
        user_id=u.id, broker="T", trade_date=d, source="MANUAL",
        corretagem=0, emolumentos=0, taxa_liquidacao=0, taxa_registro=0,
        iss=0, outras=0, irrf_day=Decimal(str(irrf_day)),
        irrf_swing=Decimal(str(irrf_swing)), net_value=0,
    )
    db.session.add(note)
    db.session.flush()
    for asset, market, side, qty, price in trades:
        db.session.add(Trade(
            user_id=u.id, note_id=note.id, trade_date=d, asset=asset, market=market,
            side=side, quantity=Decimal(str(qty)), price=Decimal(str(price)),
            gross_value=Decimal(str(qty)) * Decimal(str(price)),
        ))
    db.session.commit()
    return note


def _compute(u):
    notes = (BrokerageNote.query.filter_by(user_id=u.id)
             .order_by(BrokerageNote.trade_date).all())
    return tax_engine.compute(notes)


# --------------------------------------------------------------------------- #
def test_preco_medio_ponderado(user):
    """Compra 100@10 e 100@20 => PM 15; vende 100@25 => lucro 1000; sobra 100@15."""
    _add(user, date(2026, 1, 5), [("AAAA4", "VISTA", "C", 100, 10)])
    _add(user, date(2026, 1, 6), [("AAAA4", "VISTA", "C", 100, 20)])
    _add(user, date(2026, 2, 5), [("AAAA4", "VISTA", "V", 100, 25)])
    r = _compute(user)
    pos = {p.asset: p for p in r.positions}
    assert pos["AAAA4"].avg_price == Decimal("15")
    assert pos["AAAA4"].qty == Decimal("100")
    assert r.swing_sales[0].result == Decimal("1000")


def test_day_trade_detectado(user):
    """Compra e venda do mesmo ativo no mesmo dia => day trade, sem posição."""
    _add(user, date(2026, 3, 4),
         [("BBBB3", "VISTA", "C", 100, 10), ("BBBB3", "VISTA", "V", 100, 12)])
    r = _compute(user)
    assert len(r.day_results) == 1
    assert r.day_results[0].net_result == Decimal("200")
    assert r.positions == []
    assert r.swing_sales == []


def test_isencao_20k_swing(user):
    """Venda de ações à vista < R$20k no mês => lucro isento, imposto zero."""
    _add(user, date(2026, 1, 5), [("CCCC4", "VISTA", "C", 100, 10)])
    _add(user, date(2026, 1, 20), [("CCCC4", "VISTA", "V", 100, 13)])  # vende 1.300
    r = _compute(user)
    jan = r.month(2026, 1)
    assert jan.exempt_result == Decimal("300")
    assert jan.swing_taxable_base == Decimal("0")
    assert jan.swing_tax == Decimal("0")


def test_swing_tributavel_15pct(user):
    """Venda > R$20k com lucro 6000 => imposto 15% = 900."""
    _add(user, date(2026, 1, 5), [("DDDD4", "VISTA", "C", 2000, 10)])
    _add(user, date(2026, 2, 5), [("DDDD4", "VISTA", "V", 2000, 13)])  # vende 26.000
    r = _compute(user)
    fev = r.month(2026, 2)
    assert fev.swing_taxable_base == Decimal("6000")
    assert fev.swing_tax == Decimal("900.00")


def test_day_trade_20pct(user):
    """Day trade com lucro 300 => imposto 20% = 60."""
    _add(user, date(2026, 2, 4),
         [("EEEE3", "VISTA", "C", 100, 10), ("EEEE3", "VISTA", "V", 100, 13)])
    r = _compute(user)
    fev = r.month(2026, 2)
    assert fev.day_taxable_base == Decimal("300")
    assert fev.day_tax == Decimal("60.00")


def test_compensacao_prejuizo_swing(user):
    """Prejuízo de 3000 (mês A) compensa lucro de 6000 (mês B): base 3000, imposto 450."""
    # Mês A: vende 27.000 com prejuízo -3000 (tributável, pois > 20k)
    _add(user, date(2026, 1, 5), [("FFFF4", "VISTA", "C", 3000, 10)])
    _add(user, date(2026, 1, 25), [("FFFF4", "VISTA", "V", 3000, 9)])
    # Mês B: vende 36.000 com lucro +6000
    _add(user, date(2026, 2, 5), [("FFFF4", "VISTA", "C", 3000, 10)])
    _add(user, date(2026, 2, 25), [("FFFF4", "VISTA", "V", 3000, 12)])
    r = _compute(user)
    jan = r.month(2026, 1)
    fev = r.month(2026, 2)
    assert jan.swing_loss_acc == Decimal("3000")
    assert fev.swing_loss_used == Decimal("3000")
    assert fev.swing_taxable_base == Decimal("3000")
    assert fev.swing_tax == Decimal("450.00")
    assert r.final_swing_loss == Decimal("0")


def test_buckets_day_e_swing_nao_se_misturam(user):
    """Prejuízo de day trade não compensa lucro de swing (e vice-versa)."""
    # Day trade com prejuízo -500 (mesmo dia)
    _add(user, date(2026, 1, 6),
         [("GGGG3", "VISTA", "C", 1000, 10), ("GGGG3", "VISTA", "V", 1000, 9.5)])
    # Swing tributável com lucro 6000 (> 20k)
    _add(user, date(2026, 1, 5), [("HHHH4", "VISTA", "C", 2000, 10)])
    _add(user, date(2026, 1, 27), [("HHHH4", "VISTA", "V", 2000, 13)])
    r = _compute(user)
    jan = r.month(2026, 1)
    # swing tributado normalmente (não abatido pelo prejuízo de day trade)
    assert jan.swing_tax == Decimal("900.00")
    # prejuízo de day trade vira carryforward de day
    assert jan.day_loss_acc == Decimal("500")
    assert jan.day_tax == Decimal("0")


# --------------------------------------------------------------------------- #
# Novas regras: DARF mínimo, IRRF por modalidade, FII/ETF/BDR, descoberto
# --------------------------------------------------------------------------- #
def test_darf_abaixo_de_10_acumula_para_o_mes_seguinte(user):
    """DARF < R$10 não é recolhido: acumula até atingir o mínimo."""
    # Jan: day trade lucro 30 => imposto 6 (< 10) => darf 0, acumula 6
    _add(user, date(2026, 1, 7),
         [("IIII3", "VISTA", "C", 10, 10), ("IIII3", "VISTA", "V", 10, 13)])
    # Fev: day trade lucro 30 => imposto 6 + 6 acumulado = 12 => darf 12
    _add(user, date(2026, 2, 4),
         [("IIII3", "VISTA", "C", 10, 10), ("IIII3", "VISTA", "V", 10, 13)])
    r = _compute(user)
    jan, fev = r.month(2026, 1), r.month(2026, 2)
    assert jan.darf == Decimal("0")
    assert jan.darf_below_min is True
    assert fev.darf_carried_in == Decimal("6.00")
    assert fev.darf == Decimal("12.00")
    assert fev.darf_below_min is False


def test_irrf_day_nao_abate_imposto_de_swing(user):
    """IRRF de day trade (1%) só compensa imposto de day trade."""
    # Swing tributável: lucro 6000 (vendas 36k > 20k) => imposto 900
    _add(user, date(2026, 1, 5), [("JJJJ4", "VISTA", "C", 3000, 10)])
    _add(user, date(2026, 1, 25), [("JJJJ4", "VISTA", "V", 3000, 12)], irrf_day=50)
    r = _compute(user)
    jan = r.month(2026, 1)
    assert jan.swing_tax == Decimal("900.00")
    assert jan.irrf_day_used == Decimal("0")     # não há imposto de day p/ abater
    assert jan.darf == Decimal("900.00")          # IRRF day NÃO abateu o swing


def test_irrf_day_credito_acumula_para_mes_seguinte(user):
    """IRRF de day não usado no mês fica de crédito p/ o day dos meses seguintes."""
    # Jan: day trade com prejuízo, mas IRRF retido de 20
    _add(user, date(2026, 1, 8),
         [("KKKK3", "VISTA", "C", 100, 10), ("KKKK3", "VISTA", "V", 100, 9)], irrf_day=20)
    # Fev: day trade lucro 1000 => base 1000-100(prej.) = 900 => imposto 180 - 20 = 160
    _add(user, date(2026, 2, 10),
         [("KKKK3", "VISTA", "C", 100, 10), ("KKKK3", "VISTA", "V", 100, 20)])
    r = _compute(user)
    fev = r.month(2026, 2)
    assert fev.day_taxable_base == Decimal("900")
    assert fev.irrf_day_used == Decimal("20")
    assert fev.darf == Decimal("160.00")


def test_fii_20pct_sem_isencao(user):
    """FII: 20% mesmo com vendas abaixo de 20k (sem isenção)."""
    _add(user, date(2026, 1, 5), [("HGLG11", "VISTA", "C", 100, 100)])
    _add(user, date(2026, 1, 20), [("HGLG11", "VISTA", "V", 100, 110)])  # vende 11k, lucro 1k
    r = _compute(user)
    jan = r.month(2026, 1)
    assert jan.fii_result == Decimal("1000")
    assert jan.exempt_result == Decimal("0")
    assert jan.fii_tax == Decimal("200.00")      # 20%, sem isenção
    assert jan.swing_tax == Decimal("0")


def test_prejuizo_fii_nao_compensa_acao(user):
    """Prejuízo de FII fica no bucket de FII; não abate swing de ações."""
    # Jan: FII com prejuízo -1000
    _add(user, date(2026, 1, 5), [("MXRF11", "VISTA", "C", 1000, 10)])
    _add(user, date(2026, 1, 20), [("MXRF11", "VISTA", "V", 1000, 9)])
    # Fev: ação com lucro 6000 tributável (> 20k)
    _add(user, date(2026, 2, 5), [("LLLL4", "VISTA", "C", 3000, 10)])
    _add(user, date(2026, 2, 25), [("LLLL4", "VISTA", "V", 3000, 12)])
    r = _compute(user)
    fev = r.month(2026, 2)
    assert fev.swing_tax == Decimal("900.00")     # cheio: prejuízo de FII não entra
    assert fev.fii_loss_acc == Decimal("1000")    # segue acumulado no bucket FII
    assert r.final_fii_loss == Decimal("1000")


def test_etf_e_bdr_sem_isencao_20k(user):
    """ETF e BDR: 15% swing mas SEM a isenção dos 20k."""
    _add(user, date(2026, 1, 5), [("BOVA11", "VISTA", "C", 50, 100)])
    _add(user, date(2026, 1, 20), [("BOVA11", "VISTA", "V", 50, 120)])   # vende 6k, lucro 1k
    _add(user, date(2026, 2, 5), [("AAPL34", "VISTA", "C", 100, 50)])
    _add(user, date(2026, 2, 20), [("AAPL34", "VISTA", "V", 100, 60)])   # vende 6k, lucro 1k
    r = _compute(user)
    jan, fev = r.month(2026, 1), r.month(2026, 2)
    assert jan.exempt_result == Decimal("0")
    assert jan.swing_tax == Decimal("150.00")    # ETF tributa mesmo < 20k
    assert fev.swing_tax == Decimal("150.00")    # BDR idem


def test_etf_renda_fixa_fica_fora_da_apuracao(user):
    """ETF de renda fixa (IR na fonte) sai da apuração, com aviso."""
    _add(user, date(2026, 1, 5), [("IMAB11", "VISTA", "C", 100, 100)])
    _add(user, date(2026, 1, 20), [("IMAB11", "VISTA", "V", 100, 110)])
    r = _compute(user)
    jan = r.month(2026, 1)
    assert jan.swing_tax == Decimal("0")
    assert jan.fii_tax == Decimal("0")
    assert any("renda fixa" in w for w in r.warnings)


def test_venda_a_descoberto_gera_aviso(user):
    """Vender mais do que a posição => aviso de venda a descoberto."""
    _add(user, date(2026, 1, 5), [("NNNN3", "VISTA", "C", 100, 10)])
    _add(user, date(2026, 2, 5), [("NNNN3", "VISTA", "V", 300, 12)])
    r = _compute(user)
    assert any("descoberto" in w and "NNNN3" in w for w in r.warnings)


def test_eventos_corporativos_split_e_bonificacao(user):
    """Desdobramento 1->10 e bonificação ajustam qty/PM sem mudar o custo total."""
    from types import SimpleNamespace
    _add(user, date(2026, 1, 5), [("OOOO3", "VISTA", "C", 100, 50)])   # custo 5000
    split = SimpleNamespace(asset="OOOO3", event_date=date(2026, 2, 1),
                            kind="DESDOBRAMENTO", factor=Decimal("10"),
                            qty=None, price=None)
    bonus = SimpleNamespace(asset="OOOO3", event_date=date(2026, 3, 1),
                            kind="BONIFICACAO", factor=None,
                            qty=Decimal("100"), price=Decimal("2"))
    notes = (BrokerageNote.query.filter_by(user_id=user.id)
             .order_by(BrokerageNote.trade_date).all())
    r = tax_engine.compute(notes, adjustments=[split, bonus])
    pos = {p.asset: p for p in r.positions}["OOOO3"]
    assert pos.qty == Decimal("1100")                       # 100*10 + 100
    assert pos.total_cost == Decimal("5200")                # 5000 + 100*2
    assert pos.avg_price == Decimal("5200") / Decimal("1100")
