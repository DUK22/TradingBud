"""PDF do relatório anual para a DIRPF (gerado pelo annual_report.build)."""
from __future__ import annotations

from fpdf import FPDF

from .darf_pdf import MESES, _brl, _lat1


def _h2(pdf, text):
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(15, 60, 45)
    pdf.cell(0, 8, _lat1(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.set_draw_color(180, 215, 200)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(2)


def _row(pdf, cells, widths, bold=False, fill=False, size=8.5):
    pdf.set_font("Helvetica", "B" if bold else "", size)
    if fill:
        pdf.set_fill_color(243, 248, 245)
    h = 6
    for (text, align), w in zip(cells, widths, strict=False):
        pdf.cell(w, h, _lat1(str(text)), border="B", align=align, fill=fill)
    pdf.ln(h)


def build(user, data) -> bytes:
    year = data["year"]
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, _lat1(f"Relatório Anual {year} - apoio à DIRPF {year + 1}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(110)
    pdf.cell(0, 5, _lat1(f"Contribuinte: {user.name}"
                         + (f" - CPF {user.cpf}" if getattr(user, "cpf", None) else "")),
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, _lat1("Renda variável - gerado pelo IR Traders. Confira com seu contador."),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)

    # ----- 1. Bens e Direitos -----
    _h2(pdf, f"1. Bens e Direitos em 31/12/{year}")
    if data["bens"]:
        widths = [22, 24, 18, 28, 38, 52]
        _row(pdf, [("Ativo", "L"), ("Grupo/Cód.", "L"), ("Qtd", "R"),
                   ("Preço médio", "R"), ("Custo total (situação 31/12)", "R"),
                   ("Classe", "L")], widths, bold=True, fill=True)
        for b in data["bens"]:
            _row(pdf, [(b["asset"], "L"), (f"{b['grupo']}/{b['codigo']}", "L"),
                       (f"{b['qty']:.0f}", "R"), (_brl(b["avg_price"]), "R"),
                       (_brl(b["total_cost"]), "R"), (b["rotulo"][:34], "L")], widths)
        pdf.ln(2)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(110)
        pdf.multi_cell(0, 4, _lat1(
            "Sugestão de discriminação (copie para o campo do programa): use o texto "
            "\"<qtd> ações/cotas de <ticker>, custo médio R$ <PM>, custo total R$ <total>, "
            "conforme notas de corretagem\". Grupo/código são sugeridos - confirme no programa."))
        pdf.set_text_color(0)
    else:
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 6, _lat1("Sem posições em aberto em 31/12."), new_x="LMARGIN", new_y="NEXT")

    # ----- 2. Renda variável mês a mês -----
    _h2(pdf, "2. Renda Variável - Operações Comuns / Day Trade / FII (mês a mês)")
    widths = [18, 26, 26, 22, 24, 24, 21, 21]
    _row(pdf, [("Mês", "L"), ("Base comum", "R"), ("Base day trade", "R"),
               ("Base FII", "R"), ("Imposto", "R"), ("IRRF comp.", "R"),
               ("DARF", "R"), ("Isento 20k", "R")], widths, bold=True, fill=True)
    for m in data["months"]:
        _row(pdf, [
            (MESES[m.month][:3], "L"),
            (_brl(m.swing_taxable_base), "R"),
            (_brl(m.day_taxable_base), "R"),
            (_brl(m.fii_taxable_base), "R"),
            (_brl(m.total_tax), "R"),
            (_brl(m.irrf_day_used + m.irrf_swing_used), "R"),
            (_brl(m.darf), "R"),
            (_brl(m.exempt_result if m.exempt_result > 0 else 0), "R"),
        ], widths)
    _row(pdf, [("Total", "L"), ("", "R"), ("", "R"), ("", "R"),
               (_brl(data["total_tax"]), "R"), (_brl(data["total_irrf"]), "R"),
               (_brl(data["total_darf"]), "R"), (_brl(data["isentos_20k"]), "R")],
         widths, bold=True)

    # ----- 3. Isentos e prejuízos -----
    _h2(pdf, "3. Rendimentos isentos e prejuízos a compensar")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(0, 5.5, _lat1(
        f"Lucros isentos em vendas de ações até R$ 20.000/mês: {_brl(data['isentos_20k'])} "
        f"- declare em \"Rendimentos Isentos e Não Tributáveis\", código 20.\n"
        f"Prejuízos a compensar em 31/12/{year} (transportar para janeiro/{year + 1}):\n"
        f"   Operações comuns (swing): {_brl(data['losses']['swing'])}\n"
        f"   Day trade: {_brl(data['losses']['day'])}\n"
        f"   FII: {_brl(data['losses']['fii'])}"))

    if data["warnings"]:
        _h2(pdf, "4. Avisos da apuração")
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(150, 100, 0)
        for w in data["warnings"]:
            pdf.multi_cell(0, 4.5, _lat1("- " + w))
        pdf.set_text_color(0)

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(130)
    pdf.multi_cell(0, 4, _lat1(
        "Documento de apoio gerado pelo IR Traders a partir das notas importadas. Não "
        "substitui a conferência de um contador nem inclui proventos (dividendos/JCP), "
        "que devem ser declarados à parte. Códigos de Bens e Direitos podem mudar a cada "
        "exercício - confirme no programa da DIRPF."))
    return bytes(pdf.output())
