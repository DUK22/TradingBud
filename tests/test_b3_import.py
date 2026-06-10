"""Testes do importador de planilha da B3 (Negociação) — .xlsx."""
import io
from decimal import Decimal

from openpyxl import Workbook

from app.models import Trade
from app.services import b3_import

HEADER = ["Data do Negócio", "Tipo de Movimentação", "Mercado", "Vencimento",
          "Instituição", "Código de Negociação", "Quantidade", "Preço", "Valor"]


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _login(client, email="t@t.com", password="password"):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


def test_parse_vista():
    buf = _xlsx([HEADER,
        ["05/05/2026", "Compra", "Mercado à Vista", "", "BANCO BTG PACTUAL S/A", "PETR4", 100, 38.50, 3850.00],
        ["06/05/2026", "Venda", "Mercado à Vista", "", "BANCO BTG PACTUAL S/A", "PETR4", 100, 40.00, 4000.00],
    ])
    out = b3_import.parse(buf, "neg.xlsx")
    ts = out["trades"]
    assert len(ts) == 2
    assert ts[0]["asset"] == "PETR4"
    assert ts[0]["side"] == "C"
    assert ts[0]["market"] == "VISTA"
    assert ts[0]["price"] == Decimal("38.50")   # valor/qtd = 3850/100
    assert ts[1]["side"] == "V"


def test_parse_futuro_fica_em_reais():
    buf = _xlsx([HEADER,
        ["03/06/2026", "Compra", "Mercado Futuro", "17/06/2026", "BANCO BTG PACTUAL S/A", "WINM26", 1, 171025.00, 34205.00],
        ["03/06/2026", "Venda", "Mercado Futuro", "17/06/2026", "BANCO BTG PACTUAL S/A", "WINM26", 1, 171020.00, 34204.00],
    ])
    ts = b3_import.parse(buf, "neg.xlsx")["trades"]
    assert ts[0]["market"] == "FUTURO"
    # preço em REAIS (valor/qtd), não em pontos -> day trade fica correto
    assert ts[0]["price"] == Decimal("34205.00")
    assert ts[1]["price"] == Decimal("34204.00")


def test_cabecalho_invalido_gera_warning():
    buf = _xlsx([["foo", "bar"], ["1", "2"]])
    out = b3_import.parse(buf, "x.xlsx")
    assert out["trades"] == []
    assert out["warnings"]


def test_rota_importa_planilha(app, client, user):
    buf = _xlsx([HEADER,
        ["05/05/2026", "Compra", "Mercado à Vista", "", "BTG", "PETR4", 100, 38.50, 3850.00],
    ])
    _login(client)
    r = client.post("/integracoes/b3/importar",
                    data={"planilha": (buf, "neg.xlsx")},
                    content_type="multipart/form-data", follow_redirects=False)
    assert r.status_code == 302
    assert Trade.query.filter_by(user_id=user.id, asset="PETR4").count() == 1


def test_reconcile_aponta_faltas_e_divergencias(user):
    from datetime import date
    from decimal import Decimal

    from app.extensions import db
    from app.models import BrokerageNote, Trade

    # App tem: compra PETR4 100@38 em 05/05 + venda VALE3 50@60 em 06/05
    for d, asset, side, qty, price in [
        (date(2026, 5, 5), "PETR4", "C", 100, 38),
        (date(2026, 5, 6), "VALE3", "V", 50, 60),
    ]:
        n = BrokerageNote(user_id=user.id, broker="T", trade_date=d, source="MANUAL")
        db.session.add(n)
        db.session.flush()
        db.session.add(Trade(user_id=user.id, note_id=n.id, trade_date=d, asset=asset,
                             market="VISTA", side=side, quantity=Decimal(qty),
                             price=Decimal(price), gross_value=Decimal(qty * price)))
    db.session.commit()

    # B3 tem: PETR4 igual; VALE3 com qty diferente; ITUB4 que não está no app
    b3_trades = [
        {"trade_date": date(2026, 5, 5), "asset": "PETR4", "side": "C",
         "quantity": 100, "gross_value": 3800},
        {"trade_date": date(2026, 5, 6), "asset": "VALE3", "side": "V",
         "quantity": 100, "gross_value": 6000},
        {"trade_date": date(2026, 5, 7), "asset": "ITUB4", "side": "C",
         "quantity": 200, "gross_value": 7000},
    ]
    app_trades = Trade.query.filter_by(user_id=user.id).all()
    rec = b3_import.reconcile(b3_trades, app_trades)

    assert rec["matched"] == 1                          # PETR4 confere
    assert [r["asset"] for r in rec["only_b3"]] == ["ITUB4"]
    assert [r["asset"] for r in rec["mismatch"]] == ["VALE3"]
    assert rec["only_app"] == []


def test_rota_conferir_nao_importa_nada(app, client, user):
    from app.models import Trade

    buf = _xlsx([HEADER,
        ["05/05/2026", "Compra", "Mercado à Vista", "", "BTG", "PETR4", 100, 38.50, 3850.00],
    ])
    _login(client)
    r = client.post("/integracoes/b3/conferir",
                    data={"planilha": (buf, "neg.xlsx")},
                    content_type="multipart/form-data", follow_redirects=True)
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "falta nota" in html.lower() or "Só na B3" in html
    assert Trade.query.count() == 0       # nada importado
