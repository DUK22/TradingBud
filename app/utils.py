"""Filtros e helpers de formatação (pt-BR)."""
from decimal import Decimal, InvalidOperation

MESES_PT = [
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def format_brl(value) -> str:
    """Formata um número como moeda brasileira: 1234.5 -> 'R$ 1.234,50'."""
    d = _to_decimal(value).quantize(Decimal("0.01"))
    sign = "-" if d < 0 else ""
    d = abs(d)
    inteiro, _, dec = f"{d:.2f}".partition(".")
    # separador de milhar
    inteiro_fmt = ""
    for i, ch in enumerate(reversed(inteiro)):
        if i and i % 3 == 0:
            inteiro_fmt = "." + inteiro_fmt
        inteiro_fmt = ch + inteiro_fmt
    return f"{sign}R$ {inteiro_fmt},{dec}"


def format_num(value, casas=2) -> str:
    d = _to_decimal(value).quantize(Decimal("1." + "0" * casas) if casas else Decimal("1"))
    inteiro, _, dec = f"{d:.{casas}f}".partition(".")
    sign = "-" if inteiro.startswith("-") else ""
    inteiro = inteiro.lstrip("-")
    inteiro_fmt = ""
    for i, ch in enumerate(reversed(inteiro)):
        if i and i % 3 == 0:
            inteiro_fmt = "." + inteiro_fmt
        inteiro_fmt = ch + inteiro_fmt
    return f"{sign}{inteiro_fmt}" + (f",{dec}" if casas else "")


def format_pct(value) -> str:
    return f"{_to_decimal(value):.2f}".replace(".", ",") + "%"


def mes_nome(m: int) -> str:
    return MESES_PT[m] if 0 < m <= 12 else str(m)


def register_filters(app):
    app.jinja_env.filters["brl"] = format_brl
    app.jinja_env.filters["num"] = format_num
    app.jinja_env.filters["pct"] = format_pct
    app.jinja_env.filters["mes"] = mes_nome
