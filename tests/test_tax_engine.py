"""Testes do engine de impostos.

Roda com pytest:        pytest -q
Ou direto (sem pytest): python tests/test_tax_engine.py
"""
import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import TestConfig
from app import create_app
from app.extensions import db
from app.models import User, BrokerageNote, Trade
from app.services import tax_engine

_app = create_app(TestConfig)
_ctx = _app.app_context()
_ctx.push()


def _fresh() -> User:
    db.drop_all()
    db.create_all()
    u = User(name="t", email="t@t.com")
    u.set_password("password")
    db.session.add(u)
    db.session.commit()
    return u


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
def test_preco_medio_ponderado():
    """Compra 100@10 e 100@20 => PM 15; vende 100@25 => lucro 1000; sobra 100@15."""
    u = _fresh()
    _add(u, date(2026, 1, 5), [("AAAA4", "VISTA", "C", 100, 10)])
    _add(u, date(2026, 1, 6), [("AAAA4", "VISTA", "C", 100, 20)])
    _add(u, date(2026, 2, 5), [("AAAA4", "VISTA", "V", 100, 25)])
    r = _compute(u)
    pos = {p.asset: p for p in r.positions}
    assert pos["AAAA4"].avg_price == Decimal("15")
    assert pos["AAAA4"].qty == Decimal("100")
    assert r.swing_sales[0].result == Decimal("1000")


def test_day_trade_detectado():
    """Compra e venda do mesmo ativo no mesmo dia => day trade, sem posição."""
    u = _fresh()
    _add(u, date(2026, 3, 4),
         [("BBBB3", "VISTA", "C", 100, 10), ("BBBB3", "VISTA", "V", 100, 12)])
    r = _compute(u)
    assert len(r.day_results) == 1
    assert r.day_results[0].net_result == Decimal("200")
    assert r.positions == []
    assert r.swing_sales == []


def test_isencao_20k_swing():
    """Venda de ações à vista < R$20k no mês => lucro isento, imposto zero."""
    u = _fresh()
    _add(u, date(2026, 1, 5), [("CCCC4", "VISTA", "C", 100, 10)])
    _add(u, date(2026, 1, 20), [("CCCC4", "VISTA", "V", 100, 13)])  # vende 1.300
    r = _compute(u)
    jan = r.month(2026, 1)
    assert jan.exempt_result == Decimal("300")
    assert jan.swing_taxable_base == Decimal("0")
    assert jan.swing_tax == Decimal("0")


def test_swing_tributavel_15pct():
    """Venda > R$20k com lucro 6000 => imposto 15% = 900."""
    u = _fresh()
    _add(u, date(2026, 1, 5), [("DDDD4", "VISTA", "C", 2000, 10)])
    _add(u, date(2026, 2, 5), [("DDDD4", "VISTA", "V", 2000, 13)])  # vende 26.000
    r = _compute(u)
    fev = r.month(2026, 2)
    assert fev.swing_taxable_base == Decimal("6000")
    assert fev.swing_tax == Decimal("900.00")


def test_day_trade_20pct():
    """Day trade com lucro 300 => imposto 20% = 60."""
    u = _fresh()
    _add(u, date(2026, 2, 4),
         [("EEEE3", "VISTA", "C", 100, 10), ("EEEE3", "VISTA", "V", 100, 13)])
    r = _compute(u)
    fev = r.month(2026, 2)
    assert fev.day_taxable_base == Decimal("300")
    assert fev.day_tax == Decimal("60.00")


def test_compensacao_prejuizo_swing():
    """Prejuízo de 3000 (mês A) compensa lucro de 6000 (mês B): base 3000, imposto 450."""
    u = _fresh()
    # Mês A: vende 27.000 com prejuízo -3000 (tributável, pois > 20k)
    _add(u, date(2026, 1, 5), [("FFFF4", "VISTA", "C", 3000, 10)])
    _add(u, date(2026, 1, 25), [("FFFF4", "VISTA", "V", 3000, 9)])
    # Mês B: vende 36.000 com lucro +6000
    _add(u, date(2026, 2, 5), [("FFFF4", "VISTA", "C", 3000, 10)])
    _add(u, date(2026, 2, 25), [("FFFF4", "VISTA", "V", 3000, 12)])
    r = _compute(u)
    jan = r.month(2026, 1)
    fev = r.month(2026, 2)
    assert jan.swing_loss_acc == Decimal("3000")
    assert fev.swing_loss_used == Decimal("3000")
    assert fev.swing_taxable_base == Decimal("3000")
    assert fev.swing_tax == Decimal("450.00")
    assert r.final_swing_loss == Decimal("0")


def test_buckets_day_e_swing_nao_se_misturam():
    """Prejuízo de day trade não compensa lucro de swing (e vice-versa)."""
    u = _fresh()
    # Day trade com prejuízo -500 (mesmo dia)
    _add(u, date(2026, 1, 6),
         [("GGGG3", "VISTA", "C", 1000, 10), ("GGGG3", "VISTA", "V", 1000, 9.5)])
    # Swing tributável com lucro 6000 (> 20k)
    _add(u, date(2026, 1, 5), [("HHHH4", "VISTA", "C", 2000, 10)])
    _add(u, date(2026, 1, 27), [("HHHH4", "VISTA", "V", 2000, 13)])
    r = _compute(u)
    jan = r.month(2026, 1)
    # swing tributado normalmente (não abatido pelo prejuízo de day trade)
    assert jan.swing_tax == Decimal("900.00")
    # prejuízo de day trade vira carryforward de day
    assert jan.day_loss_acc == Decimal("500")
    assert jan.day_tax == Decimal("0")


def _all_tests():
    return [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]


if __name__ == "__main__":
    passed = 0
    for t in _all_tests():
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERRO  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(_all_tests())} testes passaram.")
