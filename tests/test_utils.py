"""Testes dos filtros de formatação pt-BR."""
from decimal import Decimal

from app.utils import format_brl, format_num, format_pct, mes_nome


def test_format_brl_milhar_e_centavos():
    assert format_brl(1234.5) == "R$ 1.234,50"
    assert format_brl(0) == "R$ 0,00"
    assert format_brl(Decimal("1000000")) == "R$ 1.000.000,00"


def test_format_brl_negativo():
    assert format_brl(-1234.5) == "-R$ 1.234,50"


def test_format_brl_invalido_vira_zero():
    assert format_brl("abc") == "R$ 0,00"
    assert format_brl(None) == "R$ 0,00"


def test_format_num_casas():
    assert format_num(1234, 0) == "1.234"
    assert format_num(1234.5, 2) == "1.234,50"


def test_format_pct():
    assert format_pct(15) == "15,00%"


def test_mes_nome():
    assert mes_nome(1) == "Janeiro"
    assert mes_nome(12) == "Dezembro"
    assert mes_nome(13) == "13"  # fora do intervalo: devolve o número
