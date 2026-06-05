"""Modulo de OCR / leitura de Nota de Corretagem.

Suporta dois layouts SINACOR:
  - BOVESPA / acoes a vista (SinacorParser / BTGParser)
  - BM&F / futuros: mini-indice WIN, mini-dolar WDO, IND, DOL (BMFParser)

Fluxo:
    texto  = extract_text(pdf_path)   # pdfplumber
    parsed = parse_note(texto)        # ParsedNote (detecta layout/corretora)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


@dataclass
class ParsedTrade:
    asset: str
    market: str
    side: str
    quantity: Decimal
    price: Decimal
    gross_value: Decimal   # acoes: financeiro; futuros: ajuste com sinal (C=+/D=-)


@dataclass
class ParsedNote:
    broker: str = "DESCONHECIDA"
    segment: str = "BOVESPA"          # BOVESPA | BMF
    note_number: str = ""
    trade_date: date | None = None
    settlement_date: date | None = None
    corretagem: Decimal = Decimal("0")
    emolumentos: Decimal = Decimal("0")
    taxa_liquidacao: Decimal = Decimal("0")
    taxa_registro: Decimal = Decimal("0")
    iss: Decimal = Decimal("0")
    outras: Decimal = Decimal("0")
    irrf_day: Decimal = Decimal("0")
    irrf_swing: Decimal = Decimal("0")
    daytrade_gross: Decimal = Decimal("0")   # BM&F: soma dos ajustes day trade
    normal_gross: Decimal = Decimal("0")     # BM&F: soma dos ajustes posicao/normal
    net_value: Decimal = Decimal("0")
    trades: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    raw_text: str = ""


_MONEY = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}")


def to_decimal(token):
    if token is None:
        return Decimal("0")
    t = str(token).strip().rstrip("DC").strip()
    t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except Exception:
        return Decimal("0")


def find_money_after(text, label_regex):
    m = re.search(label_regex + r"[^\d\-\n]{0,40}(" + _MONEY.pattern + r")", text, re.I)
    return to_decimal(m.group(1)) if m else None


def last_money_on_line(text, label_regex):
    m = re.search(label_regex + r"[^\n]*", text, re.I)
    if not m:
        return None
    found = _MONEY.findall(m.group(0))
    return to_decimal(found[-1]) if found else None


def value_below_label(text, label_regex):
    """Layout em grade (BM&F): rotulo numa linha, valores na linha de baixo.
    Retorna o ULTIMO valor monetario da linha seguinte (totais ficam a direita)."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if re.search(label_regex, line, re.I):
            if i + 1 < len(lines):
                ms = _MONEY.findall(lines[i + 1])
                if ms:
                    return to_decimal(ms[-1])
            ms = _MONEY.findall(line)
            if ms:
                return to_decimal(ms[-1])
    return None


def parse_date_br(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def extract_text(pdf_path):
    if pdfplumber is None:
        raise RuntimeError("pdfplumber nao esta instalado.")
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# BOVESPA / acoes a vista
# --------------------------------------------------------------------------- #
TICKER_RE = re.compile(r"\b([A-Z]{4}\d{1,2})([A-Z]?)\b")

ROW_RE = re.compile(
    r"""(?P<bolsa>BOVESPA|B3|BM&FBOVESPA|BMF)\s+
        (?P<cv>[CV])\s+
        (?P<market>FRACIONARIO|VISTA|OPCAO\s+DE\s+COMPRA|OPCAO\s+DE\s+VENDA|
                   OP[CC][AA]O|TERMO|EXERC[II]CIO)\s+
        (?P<spec>.+?)\s+
        (?P<qty>\d{1,3}(?:\.\d{3})*|\d+)\s+
        (?P<price>\d{1,3}(?:\.\d{3})*,\d{1,4})\s+
        (?P<value>\d{1,3}(?:\.\d{3})*,\d{2})\s+
        (?P<dc>[DC])\b""",
    re.X | re.I,
)


def _market_norm(raw):
    raw = raw.upper()
    if "FRACION" in raw:
        return "FRACIONARIO"
    if "OP" in raw and "O" in raw and ("CAO" in raw or "CO" in raw):
        return "OPCAO"
    if "TERMO" in raw:
        return "TERMO"
    return "VISTA"


def _common_header(note, text):
    m = re.search(r"N[\xba\xb0o]\s*[:\s]*nota[^\d]*(\d+)", text, re.I) or \
        re.search(r"Nr\.?\s*nota[^\d]*?(\d{3,})", text, re.I) or \
        re.search(r"N[u\xfa]mero da nota[^\d]*(\d+)", text, re.I)
    if m:
        note.note_number = m.group(1)
    m = re.search(r"(?:Data\s+preg[a\xe3]o|Preg[a\xe3]o)\D*?(\d{2}/\d{2}/\d{4})", text, re.I)
    if m:
        note.trade_date = parse_date_br(m.group(1))
    if note.trade_date is None:
        m = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", text)
        if m:
            note.trade_date = parse_date_br(m.group(1))


class SinacorParser:
    broker_name = "SINACOR"
    aliases = ("SINACOR",)

    def parse(self, text):
        note = ParsedNote(broker=self.broker_name, segment="BOVESPA", raw_text=text[:20000])
        _common_header(note, text)
        m = re.search(r"L[i\xed]quido\s+para\s+(\d{2}/\d{2}/\d{4})", text, re.I)
        if m:
            note.settlement_date = parse_date_br(m.group(1))

        for rm in ROW_RE.finditer(text):
            spec = rm.group("spec")
            tk = TICKER_RE.search(spec)
            asset = tk.group(1) if tk else spec.split()[0][:12].upper()
            qty_raw = rm.group("qty")
            quantity = to_decimal(qty_raw + ",00") if "," not in qty_raw else to_decimal(qty_raw)
            note.trades.append(ParsedTrade(
                asset=asset, market=_market_norm(rm.group("market")),
                side=rm.group("cv").upper(), quantity=quantity,
                price=to_decimal(rm.group("price")),
                gross_value=to_decimal(rm.group("value")),
            ))
        if not note.trades:
            note.warnings.append(
                "Nenhuma linha de negocio reconhecida - layout pode exigir calibracao.")

        note.corretagem = find_money_after(text, r"Corretagem") or Decimal("0")
        note.taxa_liquidacao = find_money_after(text, r"Taxa\s+de\s+[lL]iquida[c\xe7][a\xe3]o") or Decimal("0")
        note.taxa_registro = find_money_after(text, r"Taxa\s+de\s+[rR]egistro") or Decimal("0")
        note.emolumentos = find_money_after(text, r"Emolumentos") or Decimal("0")
        note.outras = find_money_after(text, r"Taxa\s+A\.?N\.?A") or Decimal("0")
        note.iss = find_money_after(text, r"\bISS\b") or Decimal("0")

        irrf_dt = last_money_on_line(text, r"IRRF[^\n]*Day\s*Trade") \
            or last_money_on_line(text, r"I\.?R\.?R\.?F[^\n]*Day")
        irrf_general = last_money_on_line(text, r"I\.?R\.?R\.?F")
        note.irrf_day = irrf_dt or Decimal("0")
        note.irrf_swing = (irrf_general if (irrf_general is not None
                           and irrf_general != note.irrf_day) else Decimal("0"))
        note.net_value = last_money_on_line(text, r"L[i\xed]quido\s+para") or Decimal("0")
        return note


class BTGParser(SinacorParser):
    broker_name = "BTG"
    aliases = ("BTG", "BTG PACTUAL", "BANCO BTG")


# --------------------------------------------------------------------------- #
# BM&F / futuros (WIN, WDO, IND, DOL ...)
# --------------------------------------------------------------------------- #
BMF_ROW = re.compile(
    r"^\s*(?P<cv>[CV])\s+"
    r"(?P<ticker>[A-Z]{2,4}[A-Z0-9]{1,4})\s+"
    r"(?P<venc>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<qty>\d{1,3}(?:\.\d{3})*)\s+"
    r"(?P<price>\d{1,3}(?:\.\d{3})*,\d{2,4})\s+"
    r"(?P<tipo>DAY\s*TRADE|DAYTRADE|NORMAL|SWING|POSICAO)\s+"
    r"(?P<valor>\d{1,3}(?:\.\d{3})*,\d{2})\s*"
    r"(?P<dc>[CD])?"
    r"(?:\s+(?P<taxaop>\d{1,3}(?:\.\d{3})*,\d{2}))?\s*$",
    re.M | re.I,
)


class BMFParser:
    broker_name = "BTG"

    def parse(self, text):
        note = ParsedNote(broker="BTG", segment="BMF", raw_text=text[:20000])
        _common_header(note, text)
        note.settlement_date = note.trade_date

        day_gross = Decimal("0")
        normal_gross = Decimal("0")
        for rm in BMF_ROW.finditer(text):
            valor = to_decimal(rm.group("valor"))
            dc = (rm.group("dc") or "").upper()
            ajuste = -valor if dc == "D" else valor      # C (ou sem marca) = credito/ganho
            tipo = rm.group("tipo").upper()
            note.trades.append(ParsedTrade(
                asset=rm.group("ticker").upper(), market="FUTURO",
                side=rm.group("cv").upper(), quantity=to_decimal(rm.group("qty")),
                price=to_decimal(rm.group("price")), gross_value=ajuste,
            ))
            if "DAY" in tipo:
                day_gross += ajuste
            else:
                normal_gross += ajuste

        note.daytrade_gross = day_gross
        note.normal_gross = normal_gross

        # Custos e liquido (grade BM&F: rotulo em cima, valor embaixo, total a direita)
        # "Total das despesas" é o rótulo mais à direita da sua linha -> último valor confiável.
        # Já engloba taxas BM&F (registro+emolumentos) e corretagem antes do IRRF.
        total_costs = value_below_label(text, r"Total das despesas") or Decimal("0")
        note.emolumentos = total_costs            # custos operacionais BM&F (lump)
        note.net_value = value_below_label(text, r"Total l[i\xed]quido da nota") or Decimal("0")

        # IRRF day trade: gross - custos - liquido (robusto p/ variacoes de rotulo)
        gross_total = day_gross + normal_gross
        irrf = gross_total - total_costs - note.net_value
        note.irrf_day = irrf if irrf > Decimal("0") else (
            value_below_label(text, r"IRRF\s+Day\s*Trade") or Decimal("0"))

        if not note.trades:
            note.warnings.append(
                "Nota BM&F nao reconhecida - layout pode exigir calibracao.")
        return note


# --------------------------------------------------------------------------- #
# Deteccao e API
# --------------------------------------------------------------------------- #
BMF_PARSER = BMFParser()
PARSERS = [BTGParser(), SinacorParser()]

_BMF_HINT = re.compile(
    r"BM&F|TAXAS?\s+BM&F|AJUSTE\s+DAY\s+TRADE|TIPO\s+NEG[O\xd3]CIO|"
    r"MERCADORIA\s+VENCIMENTO|\b(?:WIN|WDO|IND|DOL|WSP|BGI)[FGHJKMNQUVXZ]\d{2}\b",
    re.I,
)


def detect_parser(text):
    if _BMF_HINT.search(text):
        return BMF_PARSER
    up = text.upper()
    for p in PARSERS:
        if any(a in up for a in p.aliases):
            return p
    return PARSERS[0]


def parse_note(text):
    parser = detect_parser(text)
    note = parser.parse(text)
    if getattr(parser, "broker_name", "SINACOR") != "SINACOR":
        note.broker = parser.broker_name
    return note


def parse_pdf(pdf_path):
    return parse_note(extract_text(pdf_path))
