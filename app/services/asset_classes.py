"""Classificação de ativos da B3 por ticker (heurística documentada).

Por que isso importa: a tributação difere por tipo de ativo —
  - AÇÃO   : 15% swing (isenção de R$20k/mês em vendas à vista), 20% day trade.
  - FII    : 20% (swing e day), SEM isenção, prejuízo só compensa FII.
  - ETF    : 15% swing SEM isenção, 20% day trade (ETFs de renda variável).
  - ETF_RF : ETF de renda fixa — IR retido NA FONTE (fora da apuração mensal).
  - BDR    : 15% swing SEM isenção, 20% day trade.

A B3 não codifica o tipo no ticker de forma inequívoca: o sufixo "11" é usado
por FIIs, ETFs e Units. Usamos listas curadas para ETFs e Units conhecidos;
o restante com sufixo 11 é tratado como FII (caso mais comum). Mantenha as
listas atualizadas conforme necessário.
"""
from __future__ import annotations

import re

ACAO = "ACAO"
FII = "FII"
ETF = "ETF"
ETF_RF = "ETF_RF"
BDR = "BDR"

# ETFs de RENDA VARIÁVEL mais negociados (sufixo 11)
KNOWN_ETFS = {
    "BOVA11", "BOVB11", "BOVV11", "BRAX11", "ECOO11", "DIVO11", "FIND11",
    "GOVE11", "ISUS11", "MATB11", "PIBB11", "SMAL11", "SMAC11", "XBOV11",
    "IVVB11", "SPXI11", "NASD11", "EURP11", "ACWI11", "WRLD11", "USTK11",
    "TECK11", "HASH11", "QBTC11", "QETH11", "GOLD11", "BBSD11", "XINA11",
    "JOGO11", "ESGB11",
}

# ETFs de RENDA FIXA (IR na fonte — ficam FORA da apuração mensal/DARF)
KNOWN_ETFS_RF = {
    "IMAB11", "IMBB11", "IRFM11", "IB5M11", "B5P211", "LFTS11", "FIXA11",
    "NTNS11", "TESE11", "DEBB11",
}

# Units (= pacote de ações ON+PN; tributa como AÇÃO, inclusive isenção de 20k)
KNOWN_UNITS = {
    "SANB11", "TAEE11", "KLBN11", "ALUP11", "SAPR11", "ENGI11", "BPAC11",
    "IGTI11", "RNEW11", "PPLA11", "AZTE11",
}

_SUFFIX_RE = re.compile(r"^[A-Z]{4}(\d{1,2})$")
_BDR_SUFFIXES = {"31", "32", "33", "34", "35", "39"}


def classify(ticker: str | None) -> str:
    """Classifica o ticker em ACAO | FII | ETF | ETF_RF | BDR.

    Heurística: sufixos 31-39 => BDR; sufixo 11 => ETF/Unit conhecidos pelas
    listas, senão FII; demais => AÇÃO."""
    t = (ticker or "").upper().strip()
    if t in KNOWN_ETFS:
        return ETF
    if t in KNOWN_ETFS_RF:
        return ETF_RF
    if t in KNOWN_UNITS:
        return ACAO
    m = _SUFFIX_RE.match(t)
    if not m:
        return ACAO
    suffix = m.group(1)
    if suffix in _BDR_SUFFIXES:
        return BDR
    if suffix == "11":
        return FII
    return ACAO
