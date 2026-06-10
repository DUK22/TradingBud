"""Testes do mapeamento B3 -> modelo interno (to_trades)."""
from datetime import date
from decimal import Decimal

from app.services.b3_client import B3Config, B3InvestidorClient, sync_status


def test_to_trades_mapeia_compra_e_venda():
    payload = {"negociacoes": [
        {"ticker": "petr4", "tipoMovimentacao": "Compra", "quantidade": 100,
         "precoUnitario": 38.5, "data": "2026-05-04", "mercado": "Mercado à Vista"},
        {"ticker": "VALE3", "tipoMovimentacao": "Venda", "quantidade": 50,
         "precoUnitario": 60, "data": "2026-05-05", "mercado": "Fracionário"},
    ]}
    out = B3InvestidorClient.to_trades(payload)
    assert len(out) == 2
    compra, venda = out
    assert compra["asset"] == "PETR4"          # normaliza p/ maiúsculas
    assert compra["side"] == "C"
    assert compra["quantity"] == Decimal("100")
    assert compra["price"] == Decimal("38.5")
    assert compra["gross_value"] == Decimal("3850.0")
    assert compra["market"] == "VISTA"
    assert compra["trade_date"] == date(2026, 5, 4)
    assert venda["side"] == "V"
    assert venda["market"] == "FRACIONARIO"


def test_to_trades_payload_vazio():
    assert B3InvestidorClient.to_trades({}) == []


def test_sync_status_indisponivel_sem_credenciais():
    cfg = B3Config(base_url="x", client_id="", client_secret="", enabled=False)
    status = sync_status(None, cfg)
    assert status["available"] is False


def test_sync_status_disponivel():
    cfg = B3Config(base_url="x", client_id="abc", client_secret="s", enabled=True)
    status = sync_status(None, cfg)
    assert status["available"] is True
    assert status["status"] == "disconnected"
