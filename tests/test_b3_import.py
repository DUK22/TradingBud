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
