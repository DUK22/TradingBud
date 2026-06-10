"""Utilidades da integração B3 (Área do Investidor).

O acesso programático oficial da B3 segue restrito a convênios — para pessoa
física, o caminho suportado é a importação das planilhas (Negociação e
Movimentação), já implementada em b3_import/income_import. Aqui ficam apenas:

  - B3Config / sync_status: estado exibido na tela de Integrações.
  - to_trades: mapeamento payload -> modelo interno (usado pela importação e
    pronto para um eventual acesso direto à API no futuro).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class B3Config:
    base_url: str
    client_id: str
    client_secret: str
    enabled: bool = False

    @classmethod
    def from_app_config(cls, config) -> B3Config:
        return cls(
            base_url=config.get("B3_API_BASE_URL", ""),
            client_id=config.get("B3_CLIENT_ID", ""),
            client_secret=config.get("B3_CLIENT_SECRET", ""),
            enabled=config.get("B3_ENABLED", False),
        )


class B3IntegrationError(RuntimeError):
    pass


class B3InvestidorClient:
    """Mapeamentos do formato da B3 para o modelo interno."""

    def __init__(self, cfg: B3Config):
        self.cfg = cfg

    @classmethod
    def from_config(cls, app_config) -> B3InvestidorClient:
        return cls(B3Config.from_app_config(app_config))

    @staticmethod
    def to_trades(payload: dict) -> list:
        """Converte negociações (formato B3) em dicts do modelo interno."""
        out = []
        for item in (payload or {}).get("negociacoes", []):
            side = "C" if "compra" in str(item.get("tipoMovimentacao", "")).lower() else "V"
            mercado = str(item.get("mercado", "")).lower()
            if "fracion" in mercado:
                market = "FRACIONARIO"
            elif "opc" in mercado or "opç" in mercado:
                market = "OPCAO"
            elif "termo" in mercado:
                market = "TERMO"
            else:
                market = "VISTA"
            qty = Decimal(str(item.get("quantidade", 0)))
            price = Decimal(str(item.get("precoUnitario", 0)))
            out.append({
                "asset": str(item.get("ticker", "")).upper().strip(),
                "side": side,
                "market": market,
                "quantity": qty,
                "price": price,
                "gross_value": qty * price,
                "trade_date": datetime.strptime(item["data"], "%Y-%m-%d").date()
                if item.get("data") else None,
            })
        return out


def sync_status(connection, cfg: B3Config) -> dict:
    """Estado mostrado na tela de Integrações."""
    available = bool(cfg.enabled and cfg.client_id and cfg.client_secret)
    status = getattr(connection, "status", None) or "disconnected"
    return {
        "available": available,
        "status": status if available else "unavailable",
        "last_sync_at": getattr(connection, "last_sync_at", None),
        "last_message": getattr(connection, "last_message", None),
    }
