"""Stub de integração com a B3 — Área do Investidor.

Objetivo: deixar a arquitetura PRONTA para sincronização automática das
negociações, sem acoplar o resto do sistema. Hoje a B3 expõe os dados ao
investidor via portal/CEI; o acesso programático oficial depende de
convênio/credenciais (OAuth2). Quando disponível, basta implementar os
métodos marcados com NotImplementedError — o mapeamento para o modelo
interno (to_trades) já está pronto.

Uso previsto:
    client = B3InvestidorClient.from_config(app.config)
    client.authenticate(consent_token)          # OAuth2 (a implementar)
    payload = client.get_movements(cpf, ini, fim)
    trades  = client.to_trades(payload)         # -> dicts no formato interno
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass
class B3Config:
    base_url: str
    client_id: str
    client_secret: str
    enabled: bool = False

    @classmethod
    def from_app_config(cls, config) -> "B3Config":
        return cls(
            base_url=config.get("B3_API_BASE_URL", ""),
            client_id=config.get("B3_CLIENT_ID", ""),
            client_secret=config.get("B3_CLIENT_SECRET", ""),
            enabled=config.get("B3_ENABLED", False),
        )


class B3IntegrationError(RuntimeError):
    pass


class B3InvestidorClient:
    """Cliente da Área do Investidor da B3 (placeholder)."""

    def __init__(self, cfg: B3Config):
        self.cfg = cfg

    @classmethod
    def from_config(cls, app_config) -> "B3InvestidorClient":
        return cls(B3Config.from_app_config(app_config))

    # --- A IMPLEMENTAR quando o acesso oficial estiver disponível ---
    def authenticate(self, consent_token: str) -> dict:
        """Troca o consentimento do investidor por access/refresh token (OAuth2)."""
        raise NotImplementedError(
            "Integração B3 ainda não habilitada. Configure B3_CLIENT_ID/SECRET e "
            "implemente o fluxo OAuth2 da Área do Investidor."
        )

    def get_movements(self, cpf: str, start: date, end: date) -> dict:
        """Busca negociações/movimentações no período (JSON da B3)."""
        raise NotImplementedError("Endpoint de negociações da B3 a implementar.")

    # --- JÁ PRONTO: mapeamento p/ o modelo interno ---
    @staticmethod
    def to_trades(payload: dict) -> list:
        """Converte o payload da B3 para a lista de dicts usada pelo importador.

        Espera algo como:
            {"negociacoes": [
                {"ticker": "PETR4", "tipoMovimentacao": "Compra",
                 "quantidade": 100, "precoUnitario": 38.50,
                 "data": "2026-05-04", "mercado": "Mercado à Vista"}, ...]}

        Retorna dicts no formato consumido por importar_trades():
            {asset, side, quantity, price, gross_value, market, trade_date}
        """
        out = []
        for item in payload.get("negociacoes", []):
            side = "C" if str(item.get("tipoMovimentacao", "")).lower().startswith("compra") else "V"
            qty = Decimal(str(item.get("quantidade", 0)))
            price = Decimal(str(item.get("precoUnitario", 0)))
            d = item.get("data")
            try:
                td = datetime.strptime(d, "%Y-%m-%d").date() if d else None
            except ValueError:
                td = None
            mkt = str(item.get("mercado", "")).upper()
            market = "FRACIONARIO" if "FRACION" in mkt else ("OPCAO" if "OP" in mkt else "VISTA")
            out.append({
                "asset": item.get("ticker", "").upper(),
                "side": side,
                "quantity": qty,
                "price": price,
                "gross_value": qty * price,
                "market": market,
                "trade_date": td,
            })
        return out


def sync_status(connection, cfg: B3Config) -> dict:
    """Resumo do estado da integração para a UI."""
    if not cfg.enabled or not cfg.client_id:
        return {"available": False,
                "message": "Integração não configurada (defina B3_ENABLED=1 e credenciais)."}
    status = connection.status if connection else "disconnected"
    return {"available": True, "status": status,
            "message": (connection.last_message if connection else "Pronto para conectar.")}
