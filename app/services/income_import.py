"""Importa PROVENTOS da planilha de Movimentação da B3 (Extratos > Movimentação).

A planilha lista todos os eventos da conta; aqui filtramos só os créditos de
proventos: Dividendo, Juros Sobre Capital Próprio (JCP) e Rendimento (FII).

Colunas típicas (casadas de forma flexível, sem acento/minúsculas):
    Entrada/Saída | Data | Movimentação | Produto | Instituição |
    Quantidade | Preço unitário | Valor da Operação

O ticker vem do início de "Produto" (ex.: "PETR4 - PETROBRAS PN").
"""
from __future__ import annotations

import re

from .b3_import import _norm, _rows_from_csv, _rows_from_xlsx, _to_date, _to_decimal

KIND_DIVIDENDO = "DIVIDENDO"
KIND_JCP = "JCP"
KIND_RENDIMENTO = "RENDIMENTO"

_TICKER_RE = re.compile(r"^([A-Z0-9]{4,8})\b")


def _kind(movimentacao: str) -> str | None:
    m = _norm(movimentacao)
    if "juros sobre capital" in m or m == "jcp":
        return KIND_JCP
    if "dividendo" in m:
        return KIND_DIVIDENDO
    if "rendimento" in m:
        return KIND_RENDIMENTO
    return None


def _match_columns(header: list) -> dict:
    cols = {}
    for i, raw in enumerate(header or []):
        h = _norm(raw)
        if not h:
            continue
        if "entrada" in h and "saida" in h:
            cols["inout"] = i
        elif h == "data" or h.startswith("data"):
            cols.setdefault("date", i)
        elif "movimenta" in h:
            cols["movement"] = i
        elif "produto" in h:
            cols["product"] = i
        elif "institui" in h:
            cols["broker"] = i
        elif "valor" in h:
            cols["value"] = i
    return cols


def parse(stream, filename: str) -> dict:
    """Lê a planilha de Movimentação e devolve {'incomes': [...], 'warnings': [...]}.

    Cada item: dict(income_date, asset, kind, value, broker)."""
    name = (filename or "").lower()
    rows = _rows_from_xlsx(stream) if name.endswith(".xlsx") else _rows_from_csv(stream)

    header_idx, cols = None, {}
    for i, row in enumerate(rows[:15]):
        c = _match_columns(row)
        if "movement" in c and "product" in c and "value" in c:
            header_idx, cols = i, c
            break
    if header_idx is None:
        return {"incomes": [], "warnings": [
            "Não reconheci o cabeçalho. Envie o extrato de MOVIMENTAÇÃO da B3 "
            "(Extratos > Movimentação), em .xlsx ou .csv."]}

    incomes, warnings, ignored = [], [], 0
    for row in rows[header_idx + 1:]:
        if not row or all(v in (None, "") for v in row):
            continue

        def col(key, _row=row):
            i = cols.get(key)
            return _row[i] if i is not None and i < len(_row) else None

        kind = _kind(str(col("movement") or ""))
        if kind is None:
            ignored += 1
            continue
        inout = _norm(str(col("inout") or "credito"))
        if "credito" not in inout:        # só entradas (créditos)
            continue
        d = _to_date(col("date"))
        value = _to_decimal(col("value"))
        m = _TICKER_RE.match(str(col("product") or "").upper().strip())
        asset = m.group(1) if m else ""
        if not d or not asset or value <= 0:
            continue
        incomes.append({
            "income_date": d, "asset": asset, "kind": kind, "value": value,
            "broker": str(col("broker") or "").strip()[:60],
        })

    if not incomes:
        warnings.append("Nenhum provento (dividendo/JCP/rendimento) encontrado "
                        "no arquivo — confira se é o extrato de Movimentação.")
    return {"incomes": incomes, "warnings": warnings}
