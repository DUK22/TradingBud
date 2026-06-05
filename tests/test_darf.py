"""Testes do DARF em PDF (rota + geração) e do cálculo de vencimento."""
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import BrokerageNote, Trade
from app.services import darf_pdf


def _login(client, email="t@t.com", password="password"):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


def _day_trade(user, d):
    note = BrokerageNote(user_id=user.id, broker="T", trade_date=d, source="MANUAL")
    db.session.add(note)
    db.session.flush()
    for side, price in (("C", 10), ("V", 12)):
        db.session.add(Trade(user_id=user.id, note_id=note.id, trade_date=d,
                             asset="PETR4", market="VISTA", side=side,
                             quantity=Decimal("100"), price=Decimal(price),
                             gross_value=Decimal("100") * Decimal(price)))
    db.session.commit()


def test_vencimento_ultimo_dia_util():
    # Apuração de junho/2026 -> vence no último dia útil de julho/2026 (sex 31/07)
    assert darf_pdf.vencimento_darf(2026, 6) == date(2026, 7, 31)
    # Dezembro vira janeiro do ano seguinte
    assert darf_pdf.vencimento_darf(2026, 12).month == 1


def test_darf_pdf_download(app, client, user):
    _day_trade(user, date(2026, 1, 5))
    _login(client)
    r = client.get("/apuracao/2026/1/darf.pdf")
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert r.get_data()[:5] == b"%PDF-"


def test_darf_pdf_mes_inexistente_404(app, client, user):
    _day_trade(user, date(2026, 1, 5))
    _login(client)
    assert client.get("/apuracao/2030/9/darf.pdf").status_code == 404
