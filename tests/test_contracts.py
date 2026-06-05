"""Testes das especificações de contratos futuros (valor do ponto / contrato)."""
from decimal import Decimal

from app.services import contracts


def test_contract_root():
    assert contracts.contract_root("WINM26") == "WIN"
    assert contracts.contract_root("WDON26") == "WDO"
    assert contracts.contract_root("DOLF26") == "DOL"
    assert contracts.contract_root("PETR4") is None      # ação, não futuro
    assert contracts.contract_root(None) is None


def test_point_value():
    assert contracts.point_value("WINM26") == Decimal("0.20")
    assert contracts.point_value("DOLF26") == Decimal("50.00")
    assert contracts.point_value("XYZ") is None


def test_contract_value():
    # WIN a 130.000 pontos, 1 contrato => 130000 * 0,20 = R$ 26.000
    assert contracts.contract_value("WINM26", 130000, 1) == Decimal("26000.00")
    # WDO a 5.500 pontos, 2 contratos => 5500 * 10 * 2 = R$ 110.000
    assert contracts.contract_value("WDON26", 5500, 2) == Decimal("110000.00")
    # ação não tem valor de ponto
    assert contracts.contract_value("PETR4", 38, 100) is None
