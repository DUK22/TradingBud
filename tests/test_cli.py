"""Testes do comando flask darf-remind."""
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import BrokerageNote, Trade
from app.services import mailer


def _day_trade(user, d, profit=1000):
    n = BrokerageNote(user_id=user.id, broker="T", trade_date=d, source="MANUAL")
    db.session.add(n)
    db.session.flush()
    for side, price in (("C", 10), ("V", 10 + profit / 100)):
        db.session.add(Trade(user_id=user.id, note_id=n.id, trade_date=d, asset="AAAA3",
                             market="VISTA", side=side, quantity=Decimal("100"),
                             price=Decimal(str(price)),
                             gross_value=Decimal("100") * Decimal(str(price))))
    db.session.commit()


def test_darf_remind_envia_email(app, user, monkeypatch):
    _day_trade(user, date(2026, 5, 7))      # lucro 1000 => DARF 200 em maio

    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subj, body: sent.append((to, subj, body)))

    runner = app.test_cli_runner()
    res = runner.invoke(args=["darf-remind", "--month", "2026-05"])
    assert "1 enviado(s)" in res.output
    assert len(sent) == 1
    to, subj, body = sent[0]
    assert to == "t@t.com"
    assert "DARF" in subj and "200,00" in subj
    assert "Vencimento" in body and "6015" in body


def test_darf_remind_sem_movimento_nao_envia(app, user, monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send", lambda *a: sent.append(a))
    res = app.test_cli_runner().invoke(args=["darf-remind", "--month", "2026-05"])
    assert sent == []
    assert "0 enviado(s)" in res.output


def test_import_mail_importa_por_remetente(app, user, monkeypatch):
    """E-mail do usuário com PDF anexo => nota importada; desconhecido ignora."""
    from datetime import date
    from decimal import Decimal

    from app.models import BrokerageNote
    from app.services import mail_import, ocr
    from app.services.ocr import ParsedNote, ParsedTrade

    monkeypatch.setenv("IMPORT_IMAP_HOST", "imap.test")
    monkeypatch.setattr(mail_import, "fetch_messages", lambda: [
        {"sender": "t@t.com", "subject": "Nota", "pdfs": [("nota.pdf", b"%PDF-1.4 x")]},
        {"sender": "estranho@x.com", "subject": "spam",
         "pdfs": [("nota.pdf", b"%PDF-1.4 x")]},
    ])
    monkeypatch.setattr(ocr, "parse_pdf", lambda path: ParsedNote(
        broker="BTG", note_number="777", trade_date=date(2026, 6, 1),
        trades=[ParsedTrade(asset="PETR4", market="VISTA", side="C",
                            quantity=Decimal("100"), price=Decimal("38"),
                            gross_value=Decimal("3800"))]))

    res = app.test_cli_runner().invoke(args=["import-mail"])
    assert "1 importada(s)" in res.output
    assert "1 remetente(s) desconhecido(s)" in res.output
    assert BrokerageNote.query.filter_by(user_id=user.id, note_number="777").count() == 1

    # Rodar de novo com o mesmo e-mail: dedupe segura
    res = app.test_cli_runner().invoke(args=["import-mail"])
    assert "1 duplicada(s)" in res.output
    assert BrokerageNote.query.filter_by(user_id=user.id).count() == 1


def test_import_mail_desligado_sem_config(app, monkeypatch):
    monkeypatch.delenv("IMPORT_IMAP_HOST", raising=False)
    res = app.test_cli_runner().invoke(args=["import-mail"])
    assert "desligado" in res.output


def test_backup_db_sqlite(app, tmp_path, monkeypatch):
    """Backup de SQLite cria arquivo e respeita a retenção."""
    import os
    import sqlite3

    # Usa um SQLite em arquivo (o TestConfig usa :memory:)
    src = tmp_path / "src.db"
    con = sqlite3.connect(src)
    con.execute("CREATE TABLE t (x int)")
    con.execute("INSERT INTO t VALUES (42)")
    con.commit()
    con.close()
    monkeypatch.setitem(app.config, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{src}")

    out = tmp_path / "bk"
    res = app.test_cli_runner().invoke(args=["backup-db", "--out", str(out), "--keep", "2"])
    assert "Backup SQLite criado" in res.output
    files = os.listdir(out)
    assert len(files) == 1
    # Conteúdo íntegro
    chk = sqlite3.connect(out / files[0])
    assert chk.execute("SELECT x FROM t").fetchone() == (42,)
    chk.close()
