"""Proventos: parser da Movimentação, rotas e integração com o relatório."""
import io
from datetime import date
from decimal import Decimal

from openpyxl import Workbook

from app.extensions import db
from app.models import Income
from app.services import income_import

HEADER = ["Entrada/Saída", "Data", "Movimentação", "Produto",
          "Instituição", "Quantidade", "Preço unitário", "Valor da Operação"]


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _sheet():
    return _xlsx([HEADER,
        ["Credito", "15/05/2026", "Dividendo", "PETR4 - PETROBRAS PN",
         "BANCO BTG", 100, 1.50, 150.00],
        ["Credito", "20/05/2026", "Juros Sobre Capital Próprio",
         "ITUB4 - ITAU UNIBANCO PN", "BANCO BTG", 200, 0.30, 60.00],
        ["Credito", "10/05/2026", "Rendimento", "HGLG11 - CSHG LOG",
         "BANCO BTG", 50, 1.10, 55.00],
        ["Credito", "12/05/2026", "Transferência - Liquidação",
         "PETR4 - PETROBRAS PN", "BANCO BTG", 100, 38.0, 3800.00],   # ignorado
        ["Debito", "16/05/2026", "Dividendo", "PETR4 - PETROBRAS PN",
         "BANCO BTG", 100, 1.50, 150.00],                            # débito: fora
    ])


def test_parse_movimentacao_filtra_proventos():
    out = income_import.parse(_sheet(), "mov.xlsx")
    kinds = sorted((i["kind"], Decimal(i["value"])) for i in out["incomes"])
    assert kinds == [("DIVIDENDO", Decimal("150")), ("JCP", Decimal("60")),
                     ("RENDIMENTO", Decimal("55"))]
    assert out["incomes"][0]["asset"] in {"PETR4", "ITUB4", "HGLG11"}


def test_rota_importa_com_dedupe(client, user):
    client.post("/login", data={"email": "t@t.com", "password": "password"})
    r = client.post("/proventos/importar", data={"planilha": (_sheet(), "mov.xlsx")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert Income.query.filter_by(user_id=user.id).count() == 3

    # Reenvio do mesmo arquivo: nada novo
    client.post("/proventos/importar", data={"planilha": (_sheet(), "mov.xlsx")},
                content_type="multipart/form-data", follow_redirects=True)
    assert Income.query.filter_by(user_id=user.id).count() == 3

    page = client.get("/proventos?ano=2026").get_data(as_text=True)
    assert "PETR4" in page and "150,00" in page


def test_relatorio_anual_inclui_proventos(client, user):
    from app.services import annual_report
    db.session.add(Income(user_id=user.id, asset="PETR4", kind="DIVIDENDO",
                          income_date=date(2026, 5, 15), value=Decimal("150")))
    db.session.add(Income(user_id=user.id, asset="HGLG11", kind="RENDIMENTO",
                          income_date=date(2025, 3, 1), value=Decimal("99")))
    db.session.commit()
    data = annual_report.build([], [], 2026, incomes=Income.query.all())
    assert data["prov_totals"]["DIVIDENDO"] == Decimal("150")
    assert data["prov_totals"]["RENDIMENTO"] == Decimal("0")   # 2025 fica fora
