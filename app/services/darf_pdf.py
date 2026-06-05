"""Gera um DARF em PDF (demonstrativo de apuração) a partir do resultado mensal.

IMPORTANTE: é um DEMONSTRATIVO preenchido para organização/conferência — não é
o DARF oficial com código de barras (esse só o sistema da Receita/SICALC emite).
Use os valores aqui para preencher/pagar via o app ou portal da Receita.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from fpdf import FPDF

from . import tax_engine
from .tax_engine import money

MESES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def _ultimo_dia_util(year: int, month: int) -> date:
    d = date(year, month, calendar.monthrange(year, month)[1])
    while d.weekday() >= 5:          # sábado/domingo -> volta para sexta
        d -= timedelta(days=1)
    return d


def vencimento_darf(ap_year: int, ap_month: int) -> date:
    """Último dia útil do mês SEGUINTE ao da apuração (sem considerar feriados)."""
    y = ap_year + (1 if ap_month == 12 else 0)
    m = 1 if ap_month == 12 else ap_month + 1
    return _ultimo_dia_util(y, m)


def _brl(v) -> str:
    s = f"{money(v):,.2f}"                         # 1,234.56
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


# A fonte core (Helvetica) usa latin-1; troca pontuação Unicode por equivalentes
# ASCII (travessão, aspas curvas, reticências) para não quebrar a geração.
_PUNCT = {"—": "-", "–": "-", "‘": "'", "’": "'",
          "“": '"', "”": '"', "…": "..."}


def _lat1(s: str) -> str:
    for k, v in _PUNCT.items():
        s = s.replace(k, v)
    # Rede de segurança: qualquer caractere fora do latin-1 vira '?'.
    return s.encode("latin-1", "replace").decode("latin-1")


def build(user, m) -> bytes:
    """Monta o PDF do DARF para uma MonthlyApuracao `m`. Retorna os bytes."""
    venc = vencimento_darf(m.year, m.month)
    base = m.day_taxable_base + m.swing_taxable_base
    irrf = m.irrf_day + m.irrf_swing

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "DARF - Demonstrativo de Apuração", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120)
    pdf.cell(0, 5, "Ganhos líquidos em renda variável - Pessoa Física",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.ln(4)

    def linha(rotulo, valor, bold=False, size=11):
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.cell(95, 8, _lat1(str(rotulo)))
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.cell(0, 8, _lat1(str(valor)), new_x="LMARGIN", new_y="NEXT")

    linha("Contribuinte", user.name)
    if getattr(user, "cpf", None):
        linha("CPF", user.cpf)
    linha("Período de apuração", f"{MESES[m.month]} de {m.year}")
    linha("Código da receita", tax_engine.DARF_CODIGO)
    linha("Vencimento", venc.strftime("%d/%m/%Y"))
    pdf.ln(3)
    pdf.set_draw_color(210)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Apuração do mês", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    linha("Resultado Day Trade", _brl(m.day_result))
    linha("Resultado Swing Trade", _brl(m.swing_result))
    linha("Parcela isenta (ações à vista)", _brl(m.exempt_result))
    linha("Prejuízo compensado", _brl(m.day_loss_used + m.swing_loss_used))
    linha("Base de cálculo (Day 20% + Swing 15%)", _brl(base))
    linha("Imposto apurado", _brl(m.total_tax))
    linha("(-) IRRF retido na fonte", _brl(irrf))
    pdf.ln(2)
    pdf.set_draw_color(210)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(3)

    pdf.set_fill_color(240, 250, 245)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(70, 12, "  VALOR A PAGAR (DARF)", border=1, fill=True)
    pdf.cell(0, 12, "  " + _brl(m.darf), border=1, fill=True,
             new_x="LMARGIN", new_y="NEXT")

    if m.darf_below_min:
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(180, 120, 0)
        pdf.multi_cell(0, 5, _lat1(
            f"Atenção: DARF abaixo de {_brl(tax_engine.DARF_MINIMO)} não é "
            "recolhido isoladamente — acumula para um mês seguinte até atingir "
            "o mínimo."))
        pdf.set_text_color(0)

    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(130)
    pdf.multi_cell(0, 4, _lat1(
        "Demonstrativo gerado pelo IR Traders para organização e conferência. "
        "Não é o DARF oficial com código de barras (emitido pelo SICALC/Receita "
        "Federal) nem constitui aconselhamento contábil ou tributário. O vencimento "
        "considera o último dia útil do mês seguinte, sem ajuste por feriados. "
        "Confira os valores com seu contador."))

    return bytes(pdf.output())
