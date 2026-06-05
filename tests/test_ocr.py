"""Testes do parser de notas (OCR) a partir de TEXTO já extraído.

Não dependem de PDFs reais: exercitam parse_note(texto), que é onde mora a
lógica frágil de reconhecimento de layout (BOVESPA e BM&F).
"""
from datetime import date
from decimal import Decimal

from app.services import ocr

BOVESPA_TXT = """\
BTG PACTUAL CTVM
Nr. nota 123456
Data pregão 04/05/2026
Negócios realizados
BOVESPA C VISTA PETR4 ON 100 38,50 3.850,00 D
BOVESPA V VISTA VALE3 ON 50 60,00 3.000,00 C
Corretagem 5,00
Taxa de liquidação 1,00
Taxa de registro 0,50
Emolumentos 0,30
ISS 0,20
Líquido para 06/05/2026 6.139,00
"""

BMF_TXT = """\
NOTA DE NEGOCIACAO BM&F
Data pregão 16/06/2026
C WINM26 16/06/2026 1 171.025,00 DAY TRADE 21,00 D
V WINM26 16/06/2026 1 171.075,00 DAY TRADE 31,00 C
Total das despesas
4,00
Total líquido da nota
6,00
"""


def test_detecta_e_parseia_bovespa():
    note = ocr.parse_note(BOVESPA_TXT)
    assert note.segment == "BOVESPA"
    assert note.broker == "BTG"
    assert note.note_number == "123456"
    assert note.trade_date == date(2026, 5, 4)
    assert len(note.trades) == 2


def test_bovespa_primeiro_negocio():
    note = ocr.parse_note(BOVESPA_TXT)
    t = note.trades[0]
    assert t.asset == "PETR4"
    assert t.side == "C"
    assert t.market == "VISTA"
    assert t.quantity == Decimal("100")
    assert t.price == Decimal("38.50")
    assert t.gross_value == Decimal("3850.00")


def test_bovespa_custos():
    note = ocr.parse_note(BOVESPA_TXT)
    assert note.corretagem == Decimal("5.00")
    assert note.taxa_liquidacao == Decimal("1.00")
    assert note.taxa_registro == Decimal("0.50")
    assert note.emolumentos == Decimal("0.30")
    assert note.iss == Decimal("0.20")


def test_detecta_e_parseia_bmf():
    note = ocr.parse_note(BMF_TXT)
    assert note.segment == "BMF"
    assert note.broker == "BTG"
    assert len(note.trades) == 2
    # ajuste day trade: +31 (C) -21 (D) = 10
    assert note.daytrade_gross == Decimal("10.00")
    assert note.emolumentos == Decimal("4.00")   # "Total das despesas"


def test_layout_nao_reconhecido_gera_warning():
    note = ocr.parse_note("documento qualquer sem linhas de negocio\nBTG\n")
    assert note.warnings  # lista não vazia
