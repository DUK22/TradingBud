"""Pipeline de entrada de notas de corretagem (compartilhado).

Usado pela tela de upload (manual/lote), pela importação por e-mail e por
qualquer outro canal futuro. Centraliza:
  - persistência de uma ParsedNote como BrokerageNote + Trades;
  - substituição de notas provisórias pela oficial;
  - deduplicação (corretora + nº da nota + data; fallback heurístico);
  - importação de um PDF do disco (validação + OCR + dedupe).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..extensions import db
from ..models import BrokerageNote, Trade
from . import ocr


def remove_provisional(user_id, dates) -> int:
    """Remove notas provisórias do usuário nas datas informadas."""
    dates = {d for d in dates if d}
    if not dates:
        return 0
    q = BrokerageNote.query.filter(
        BrokerageNote.user_id == user_id,
        BrokerageNote.provisional.is_(True),
        BrokerageNote.trade_date.in_(dates))
    n = 0
    for note in q.all():
        db.session.delete(note)
        n += 1
    if n:
        db.session.commit()
    return n


def persist_parsed_note(user, parsed, filename=None, source="OCR") -> BrokerageNote:
    """Persiste uma ParsedNote (do OCR) como BrokerageNote + Trades."""
    note = BrokerageNote(
        user_id=user.id, broker=parsed.broker, note_number=parsed.note_number,
        trade_date=parsed.trade_date or date.today(),
        settlement_date=parsed.settlement_date, source=source,
        corretagem=parsed.corretagem, emolumentos=parsed.emolumentos,
        taxa_liquidacao=parsed.taxa_liquidacao, taxa_registro=parsed.taxa_registro,
        iss=parsed.iss, outras=parsed.outras,
        irrf_day=parsed.irrf_day, irrf_swing=parsed.irrf_swing,
        net_value=parsed.net_value, filename=filename, raw_text=parsed.raw_text,
        segment=getattr(parsed, "segment", "BOVESPA"),
        daytrade_gross=getattr(parsed, "daytrade_gross", 0),
        normal_gross=getattr(parsed, "normal_gross", 0),
    )
    db.session.add(note)
    db.session.flush()
    for t in parsed.trades:
        db.session.add(Trade(
            user_id=user.id, note_id=note.id, trade_date=note.trade_date,
            asset=t.asset, market=t.market, side=t.side,
            quantity=t.quantity, price=t.price, gross_value=t.gross_value,
        ))
    db.session.commit()
    remove_provisional(user.id, {note.trade_date})   # oficial substitui a provisória
    return note


def _d_eq(a, b) -> bool:
    return Decimal(str(a or 0)) == Decimal(str(b or 0))


def is_duplicate(user_id, parsed) -> bool:
    """Dedupe: mesma corretora + mesmo número de nota + mesma data do pregão.
    Sem número de nota, cai para (data, nº de negócios, financeiro)."""
    if parsed.note_number:
        return db.session.query(BrokerageNote.id).filter_by(
            user_id=user_id, broker=parsed.broker,
            note_number=parsed.note_number, trade_date=parsed.trade_date,
        ).first() is not None
    if not parsed.trade_date:
        return False
    same_day = BrokerageNote.query.filter_by(
        user_id=user_id, broker=parsed.broker,
        trade_date=parsed.trade_date, provisional=False).all()
    return any(len(n.trades) == len(parsed.trades)
               and _d_eq(n.net_value, parsed.net_value) for n in same_day)


def import_pdf(user, path: str, display_name: str, stored_name: str,
               source: str = "OCR") -> tuple[str, str]:
    """Importa um PDF já salvo em `path`. Retorna (status, mensagem):
    status em {'ok', 'dup', 'err'}."""
    try:
        parsed = ocr.parse_pdf(path)
    except Exception as e:  # noqa: BLE001
        return "err", f"{display_name}: falha ao ler ({e})."

    if is_duplicate(user.id, parsed):
        num = parsed.note_number or "sem número"
        return "dup", f"{display_name}: nota já importada (nº {num})."

    persist_parsed_note(user, parsed, filename=stored_name, source=source)
    msg = f"{display_name}: {len(parsed.trades)} negócio(s)."
    if parsed.warnings:
        msg += " Atenção: " + " ".join(parsed.warnings)
    return "ok", msg
