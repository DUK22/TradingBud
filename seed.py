"""Popula o banco com um usuário demo e operações de exemplo.

    python seed.py

Login:  demo@trader.com  /  demo1234

Os dados cobrem: compras/vendas swing, day trade (lucro e prejuízo),
isenção de R$20k (mês com venda de ações < 20k), compensação de prejuízo
entre meses e posições em aberto — para o dashboard nascer "vivo".
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app import create_app
from app.extensions import db
from app.models import User, BrokerageNote, Trade

app = create_app()


def cent(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def add_note(user, d, trades, irrf_day=0, irrf_swing=0, broker="BTG"):
    """trades: lista de (asset, market, side, qty, price)."""
    vol = sum(Decimal(str(q)) * Decimal(str(p)) for (_, _, _, q, p) in trades)
    emol = cent(vol * Decimal("0.00005"))       # emolumentos B3 (aprox.)
    liq = cent(vol * Decimal("0.00025"))        # taxa de liquidação CBLC (aprox.)
    note = BrokerageNote(
        user_id=user.id, broker=broker, trade_date=d, settlement_date=d,
        source="MANUAL", corretagem=Decimal("0"), emolumentos=emol,
        taxa_liquidacao=liq, taxa_registro=Decimal("0"), iss=Decimal("0"),
        outras=Decimal("0"), irrf_day=cent(irrf_day), irrf_swing=cent(irrf_swing),
        net_value=cent(vol),
    )
    db.session.add(note)
    db.session.flush()
    for asset, market, side, qty, price in trades:
        db.session.add(Trade(
            user_id=user.id, note_id=note.id, trade_date=d, asset=asset,
            market=market, side=side, quantity=Decimal(str(qty)),
            price=Decimal(str(price)), gross_value=cent(Decimal(str(qty)) * Decimal(str(price))),
        ))
    return note


def run():
    with app.app_context():
        # idempotente: remove o demo anterior
        old = User.query.filter_by(email="demo@trader.com").first()
        if old:
            db.session.delete(old)
            db.session.commit()

        user = User(name="Trader Demo", email="demo@trader.com", cpf="123.456.789-00")
        user.set_password("demo1234")
        db.session.add(user)
        db.session.flush()

        # JAN — swing isento (venda de ações à vista < R$20k): lucro 600 isento
        add_note(user, date(2026, 1, 8),  [("ITUB4", "VISTA", "C", 200, 30.00)])
        add_note(user, date(2026, 1, 22), [("ITUB4", "VISTA", "V", 200, 33.00)], irrf_swing="0.33")

        # FEV — montando posições
        add_note(user, date(2026, 2, 10), [("PETR4", "VISTA", "C", 1000, 38.00)])
        add_note(user, date(2026, 2, 12), [("VALE3", "VISTA", "C", 500, 60.00)])

        # MAR — day trade com lucro + venda swing tributável (>20k)
        add_note(user, date(2026, 3, 10),
                 [("PETR4", "VISTA", "C", 500, 39.00), ("PETR4", "VISTA", "V", 500, 39.80)],
                 irrf_day="4.00")
        add_note(user, date(2026, 3, 20), [("PETR4", "VISTA", "V", 1000, 41.00)], irrf_swing="2.05")

        # ABR — venda swing com prejuízo (gera prejuízo a compensar) + posição aberta
        add_note(user, date(2026, 4, 2),  [("MGLU3", "VISTA", "C", 1000, 12.00)])  # fica aberta
        add_note(user, date(2026, 4, 15), [("VALE3", "VISTA", "V", 500, 55.00)], irrf_swing="1.38")

        # MAI — venda swing com lucro (compensa prejuízo de abr) + day trade prejuízo + posição aberta
        add_note(user, date(2026, 5, 5),  [("PETR4", "VISTA", "C", 800, 40.00)])
        add_note(user, date(2026, 5, 6),  [("BBAS3", "VISTA", "C", 300, 28.00)])  # fica aberta
        add_note(user, date(2026, 5, 18),
                 [("VALE3", "VISTA", "C", 200, 58.00), ("VALE3", "VISTA", "V", 200, 57.00)])
        add_note(user, date(2026, 5, 28), [("PETR4", "VISTA", "V", 800, 43.00)], irrf_swing="1.72")

        # JUN — day trade no mês corrente (para o dashboard mostrar DARF do mês)
        add_note(user, date(2026, 6, 2),
                 [("PETR4", "VISTA", "C", 300, 40.00), ("PETR4", "VISTA", "V", 300, 40.60)],
                 irrf_day="1.80")

        # JUN - exemplo BM&F (mini-indice WIN, day trade) p/ demonstrar futuros
        bmf = BrokerageNote(
            user_id=user.id, broker="BTG", segment="BMF", trade_date=date(2026, 6, 3),
            settlement_date=date(2026, 6, 3), source="OCR", emolumentos=cent("4.00"),
            irrf_day=cent("0.59"), daytrade_gross=cent("63.00"), net_value=cent("58.41"),
        )
        db.session.add(bmf)
        db.session.flush()
        for cv, price, aj in [("V", "171075.00", "31.00"), ("C", "171025.00", "-21.00"),
                              ("V", "171100.00", "36.00"), ("C", "171105.00", "-37.00"),
                              ("V", "171150.00", "54.00")]:
            db.session.add(Trade(
                user_id=user.id, note_id=bmf.id, trade_date=date(2026, 6, 3), asset="WINM26",
                market="FUTURO", side=cv, quantity=Decimal("1"),
                price=Decimal(price), gross_value=Decimal(aj)))

        db.session.commit()
        n_notes = BrokerageNote.query.filter_by(user_id=user.id).count()
        n_trades = Trade.query.filter_by(user_id=user.id).count()
        print(f"OK: usuário demo criado com {n_notes} notas e {n_trades} negócios.")
        print("Login: demo@trader.com / demo1234")


if __name__ == "__main__":
    run()
