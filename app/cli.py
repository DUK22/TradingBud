"""Comandos de linha de comando (rodados por cron/agendador em produção).

    flask darf-remind [--month YYYY-MM]

Envia, para cada usuário com movimento no mês de apuração (por padrão o mês
anterior), um e-mail com o DARF calculado e o vencimento. Agende para o início
de cada mês (ex.: dia 1, 09:00). Sem MAIL_SERVER, os e-mails saem no log.
"""
from __future__ import annotations

from datetime import UTC, date

import click
from flask import Blueprint

from .extensions import db  # noqa: F401  (garante app context com modelos)
from .models import BrokerageNote, PositionAdjustment, User
from .services import mail_import, mailer, note_intake, tax_engine
from .services.darf_pdf import vencimento_darf

cli_bp = Blueprint("cli", __name__, cli_group=None)


def _prev_month(today: date) -> tuple[int, int]:
    return (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)


def _fmt(v) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def darf_email_body(user, m, venc) -> str:
    lines = [
        f"Olá, {user.name}!",
        "",
        f"Apuração de {m.month:02d}/{m.year} no IR Traders:",
        "",
        f"  Resultado day trade : {_fmt(m.day_result)}",
        f"  Resultado swing     : {_fmt(m.swing_result)}",
    ]
    if m.fii_result:
        lines.append(f"  Resultado FIIs      : {_fmt(m.fii_result)}")
    lines += [
        f"  Imposto apurado     : {_fmt(m.total_tax)}",
        f"  IRRF compensado     : {_fmt(m.irrf_day_used + m.irrf_swing_used)}",
        "",
    ]
    if m.darf > 0:
        lines += [
            f"  >>> DARF a pagar: {_fmt(m.darf)} (código 6015)",
            f"  >>> Vencimento  : {venc:%d/%m/%Y} (último dia útil do mês)",
            "",
            "Emita o DARF oficial no SICALC:",
            "https://sicalc.receita.economia.gov.br/sicalc/principal",
        ]
    elif m.darf_below_min:
        lines += [
            "  DARF abaixo de R$ 10,00 — não recolha agora; o valor acumula "
            "para o mês seguinte.",
        ]
    else:
        lines += ["  Sem DARF a pagar neste mês."]
    lines += ["", "— IR Traders (lembrete automático; confira com seu contador)"]
    return "\n".join(lines)


@cli_bp.cli.command("darf-remind")
@click.option("--month", "month_str", default=None,
              help="Mês de apuração no formato YYYY-MM (padrão: mês anterior).")
def darf_remind(month_str):
    """Envia o lembrete mensal de DARF para todos os usuários com movimento."""
    if month_str:
        year, month = int(month_str[:4]), int(month_str[5:7])
    else:
        year, month = _prev_month(date.today())
    venc = vencimento_darf(year, month)

    sent = skipped = 0
    for user in User.query.all():
        notes = (BrokerageNote.query.filter_by(user_id=user.id)
                 .order_by(BrokerageNote.trade_date.asc()).all())
        if not notes:
            continue
        adjustments = (PositionAdjustment.query.filter_by(user_id=user.id)
                       .order_by(PositionAdjustment.event_date.asc()).all())
        result = tax_engine.compute(notes, adjustments=adjustments)
        m = result.month(year, month)
        if m is None:
            skipped += 1
            continue
        subject = (f"IR Traders — DARF de {month:02d}/{year}: {_fmt(m.darf)}"
                   if m.darf > 0 else
                   f"IR Traders — apuração de {month:02d}/{year} (sem DARF)")
        mailer.send(user.email, subject, darf_email_body(user, m, venc))
        sent += 1

    click.echo(f"darf-remind {month:02d}/{year}: {sent} enviado(s), "
               f"{skipped} sem movimento no mês.")


@cli_bp.cli.command("import-mail")
def import_mail():
    """Importa notas PDF anexadas em e-mails não lidos da caixa IMAP.

    O remetente precisa ser o e-mail de uma conta cadastrada. Agende a cada
    15-30 min: */15 * * * *  cd /app && flask import-mail
    """
    import os
    from datetime import datetime

    from flask import current_app

    if not mail_import.is_configured():
        click.echo("IMPORT_IMAP_HOST não configurado — recurso desligado.")
        return

    messages = mail_import.fetch_messages()
    ok = dup = err = unknown = 0
    for m in messages:
        user = User.query.filter_by(email=m["sender"]).first()
        if user is None:
            unknown += 1
            click.echo(f"ignorado (remetente desconhecido): {m['sender']}")
            continue
        for fname, raw in m["pdfs"]:
            stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
            stored = f"{user.id}_{stamp}_{os.path.basename(fname)}"
            path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
            with open(path, "wb") as fh:
                fh.write(raw)
            status, msg = note_intake.import_pdf(user, path, fname, stored,
                                                 source="EMAIL")
            if status != "ok":
                os.remove(path)
            click.echo(f"[{user.email}] {status}: {msg}")
            ok += status == "ok"
            dup += status == "dup"
            err += status == "err"

    click.echo(f"import-mail: {ok} importada(s), {dup} duplicada(s), "
               f"{err} erro(s), {unknown} remetente(s) desconhecido(s).")
