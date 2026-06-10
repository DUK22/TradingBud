"""Relatório anual DIRPF (service + rotas + PDF)."""
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import BrokerageNote, Trade
from app.services import annual_report


def _op(user, d, asset, side, qty, price, market="VISTA"):
    n = BrokerageNote(user_id=user.id, broker="T", trade_date=d, source="MANUAL")
    db.session.add(n)
    db.session.flush()
    db.session.add(Trade(user_id=user.id, note_id=n.id, trade_date=d, asset=asset,
                         market=market, side=side, quantity=Decimal(str(qty)),
                         price=Decimal(str(price)),
                         gross_value=Decimal(str(qty)) * Decimal(str(price))))
    db.session.commit()


def _notes(user):
    return (BrokerageNote.query.filter_by(user_id=user.id)
            .order_by(BrokerageNote.trade_date).all())


def test_relatorio_corta_em_31_12_e_lista_bens(user):
    _op(user, date(2025, 3, 5), "PETR4", "C", 100, 30)      # posição de 2025
    _op(user, date(2026, 2, 5), "PETR4", "V", 100, 35)      # vendida só em 2026
    data = annual_report.build(_notes(user), [], 2025)
    assert data["year"] == 2025
    bens = {b["asset"]: b for b in data["bens"]}
    assert "PETR4" in bens                                   # ainda em carteira em 31/12/25
    assert bens["PETR4"]["total_cost"] == Decimal("3000")
    assert bens["PETR4"]["grupo"] == "03"

    data26 = annual_report.build(_notes(user), [], 2026)
    assert data26["bens"] == []                              # zerada em 2026


def test_relatorio_isentos_e_prejuizo_transportado(user):
    # 2025: prejuízo tributável (vendas > 20k)
    _op(user, date(2025, 4, 1), "VALE3", "C", 3000, 10)
    _op(user, date(2025, 4, 20), "VALE3", "V", 3000, 9)      # -3000, vendas 27k
    # 2026: lucro isento (vendas < 20k)
    _op(user, date(2026, 1, 5), "MGLU3", "C", 100, 10)
    _op(user, date(2026, 1, 20), "MGLU3", "V", 100, 30)      # +2000, vendas 3k
    d25 = annual_report.build(_notes(user), [], 2025)
    assert d25["losses"]["swing"] == Decimal("3000")
    d26 = annual_report.build(_notes(user), [], 2026)
    assert d26["isentos_20k"] == Decimal("2000")
    assert d26["losses_prev"]["swing"] == Decimal("3000")    # veio de 2025


def test_rotas_relatorio_e_pdf(client, user):
    _op(user, date(2026, 5, 5), "PETR4", "C", 100, 30)
    client.post("/login", data={"email": "t@t.com", "password": "password"})

    r = client.get("/relatorio/2026")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Bens e Direitos" in html and "PETR4" in html

    pdf = client.get("/relatorio/2026/pdf")
    assert pdf.status_code == 200
    assert pdf.data.startswith(b"%PDF")

    assert client.get("/relatorio/1999").status_code == 404
