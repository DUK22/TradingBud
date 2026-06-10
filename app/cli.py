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


@cli_bp.cli.command("backup-db")
@click.option("--out", "out_dir", default=None,
              help="Diretório de destino (padrão: instance/backups).")
@click.option("--keep", default=14, show_default=True,
              help="Quantos backups manter (os mais antigos são apagados).")
def backup_db(out_dir, keep):
    """Faz backup do banco. SQLite: cópia consistente via API de backup.
    PostgreSQL: usa pg_dump se disponível. Agende diariamente:
        0 3 * * *  cd /app && flask backup-db
    """
    import os
    import sqlite3
    import subprocess
    from datetime import datetime

    from flask import current_app

    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    out_dir = out_dir or os.path.join(current_app.instance_path, "backups")
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    if uri.startswith("sqlite:///"):
        src_path = uri.replace("sqlite:///", "", 1)
        if not os.path.exists(src_path):
            click.echo(f"Banco não encontrado: {src_path}")
            raise SystemExit(1)
        dest = os.path.join(out_dir, f"ir_traders-{stamp}.db")
        src = sqlite3.connect(src_path)
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)          # cópia consistente mesmo com app no ar
        src.close()
        dst.close()
        click.echo(f"Backup SQLite criado: {dest}")
        prefix, suffix = "ir_traders-", ".db"
    elif uri.startswith(("postgresql://", "postgresql+")):
        dest = os.path.join(out_dir, f"ir_traders-{stamp}.sql.gz")
        # pg_dump aceita URI "postgresql://"; remove o sufixo do driver SQLAlchemy
        pg_uri = "postgresql://" + uri.split("://", 1)[1]
        try:
            with open(dest, "wb") as fh:
                dump = subprocess.Popen(["pg_dump", "--no-owner", pg_uri],
                                        stdout=subprocess.PIPE)
                gzip_p = subprocess.Popen(["gzip"], stdin=dump.stdout, stdout=fh)
                dump.stdout.close()
                gzip_p.communicate()
            if gzip_p.returncode != 0 or dump.wait() != 0:
                raise RuntimeError("pg_dump/gzip retornou erro")
        except (FileNotFoundError, RuntimeError) as e:
            click.echo(f"Falha no pg_dump ({e}). Instale postgresql-client ou use "
                       "o backup gerenciado do provedor (Render/Heroku têm).")
            raise SystemExit(1) from e
        click.echo(f"Backup PostgreSQL criado: {dest}")
        prefix, suffix = "ir_traders-", ".sql.gz"
    else:
        click.echo(f"Backup automático não suportado para: {uri.split(':', 1)[0]}")
        raise SystemExit(1)

    # Retenção: mantém os `keep` mais recentes
    backups = sorted(f for f in os.listdir(out_dir)
                     if f.startswith(prefix) and f.endswith(suffix))
    for old in backups[:-keep] if keep > 0 else []:
        os.remove(os.path.join(out_dir, old))
        click.echo(f"Backup antigo removido: {old}")
