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
