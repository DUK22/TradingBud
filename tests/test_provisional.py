"""Testes da nota provisória do dia e da substituição pela oficial."""
import io
from datetime import date

from openpyxl import Workbook

from app.extensions import db
from app.models import BrokerageNote

HEADER = ["Data do Negócio", "Tipo de Movimentação", "Mercado", "Vencimento",
          "Instituição", "Código de Negociação", "Quantidade", "Preço", "Valor"]


def _login(client, email="t@t.com", password="password"):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_cria_nota_provisoria(client, user):
    _login(client)
    r = client.post("/notas/provisoria", data={
        "trade_date": "2026-01-05",
        "asset": ["PETR4", "PETR4"], "market": ["VISTA", "VISTA"],
        "side": ["C", "V"], "quantity": ["100", "100"], "price": ["38.50", "40.00"],
    }, follow_redirects=False)
    assert r.status_code == 302
    note = BrokerageNote.query.filter_by(user_id=user.id, provisional=True).first()
    assert note is not None
    assert len(note.trades) == 2
    assert note.emolumentos > 0          # custo estimado aplicado


def test_oficial_substitui_provisoria(client, user):
    _login(client)
    db.session.add(BrokerageNote(user_id=user.id, broker="PROVISÓRIA",
                                 trade_date=date(2026, 5, 5), source="MANUAL", provisional=True))
    db.session.commit()
    buf = _xlsx([HEADER,
        ["05/05/2026", "Compra", "Mercado à Vista", "", "BTG", "PETR4", 100, 38.50, 3850.00]])
    client.post("/integracoes/b3/importar", data={"planilha": (buf, "neg.xlsx")},
                content_type="multipart/form-data")
    assert BrokerageNote.query.filter_by(user_id=user.id, provisional=True).count() == 0
    assert BrokerageNote.query.filter_by(user_id=user.id, source="B3").count() == 1
