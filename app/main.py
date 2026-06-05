"""Blueprint principal: dashboard, upload/OCR, notas, apuração, posições, B3."""
import os
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from .extensions import db
from .models import B3Connection, BrokerageNote, Trade
from .services import ocr, tax_engine
from .services.b3_client import B3Config, sync_status

main_bp = Blueprint("main", __name__)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _allowed(filename: str) -> bool:
    return "." in filename and \
        filename.rsplit(".", 1)[1].lower() in current_app.config["ALLOWED_EXTENSIONS"]


def importar_parsed_note(user, parsed, filename=None, source="OCR") -> BrokerageNote:
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
    return note


def _user_notes():
    return (BrokerageNote.query
            .filter_by(user_id=current_user.id)
            .order_by(BrokerageNote.trade_date.asc())
            .all())


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@main_bp.route("/")
@login_required
def dashboard():
    notes = _user_notes()
    result = tax_engine.compute(notes)

    today = date.today()
    cur = result.month(today.year, today.month)

    patrimonio = sum((p.market_cost for p in result.positions), Decimal("0"))
    ano = today.year
    meses_ano = [m for m in result.months if m.year == ano]
    resultado_ano = sum((m.total_result for m in meses_ano), Decimal("0"))
    imposto_ano = sum((m.total_tax for m in meses_ano), Decimal("0"))

    # Série para gráficos (todos os meses)
    chart = {
        "labels": [f"{m.month:02d}/{m.year}" for m in result.months],
        "day": [float(m.day_result) for m in result.months],
        "swing": [float(m.swing_result) for m in result.months],
        "tax": [float(m.total_tax) for m in result.months],
    }
    # acumulado de resultado
    acc, serie_acc = 0.0, []
    for m in result.months:
        acc += float(m.total_result)
        serie_acc.append(round(acc, 2))
    chart["acc"] = serie_acc

    return render_template(
        "dashboard.html",
        result=result, cur=cur, patrimonio=patrimonio,
        resultado_ano=resultado_ano, imposto_ano=imposto_ano,
        ano=ano, chart=chart, n_notas=len(notes),
    )


# --------------------------------------------------------------------------- #
# Upload / OCR
# --------------------------------------------------------------------------- #
@main_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        file = request.files.get("nota")
        if not file or file.filename == "":
            flash("Selecione um arquivo PDF.", "error")
            return redirect(request.url)
        if not _allowed(file.filename):
            flash("Formato inválido. Envie um PDF.", "error")
            return redirect(request.url)

        fname = secure_filename(file.filename) or "nota.pdf"
        stamped = f"{current_user.id}_{datetime.now(UTC):%Y%m%d%H%M%S}_{fname}"
        path = os.path.join(current_app.config["UPLOAD_FOLDER"], stamped)
        file.save(path)

        # Defesa em profundidade: além da extensão, exige assinatura real de PDF.
        with open(path, "rb") as fh:
            head = fh.read(5)
        if head != b"%PDF-":
            os.remove(path)
            flash("O arquivo não é um PDF válido.", "error")
            return redirect(request.url)

        try:
            parsed = ocr.parse_pdf(path)
        except Exception as e:  # noqa: BLE001
            flash(f"Falha ao ler o PDF: {e}", "error")
            return redirect(request.url)

        note = importar_parsed_note(current_user, parsed, filename=stamped, source="OCR")
        msg = f"Nota importada: {len(parsed.trades)} negócio(s) reconhecido(s)."
        if parsed.warnings:
            msg += " Atenção: " + " ".join(parsed.warnings)
            flash(msg, "warning")
        else:
            flash(msg, "success")
        return redirect(url_for("main.note_detail", note_id=note.id))

    return render_template("upload.html")


# --------------------------------------------------------------------------- #
# Notas e negócios
# --------------------------------------------------------------------------- #
@main_bp.route("/notas")
@login_required
def notes():
    page = request.args.get("page", 1, type=int)
    pagination = (BrokerageNote.query.filter_by(user_id=current_user.id)
                  .order_by(BrokerageNote.trade_date.desc())
                  .paginate(page=page, per_page=current_app.config["ITEMS_PER_PAGE"],
                            error_out=False))
    return render_template("notes.html", pagination=pagination)


@main_bp.route("/notas/<int:note_id>")
@login_required
def note_detail(note_id):
    note = db.session.get(BrokerageNote, note_id)
    if not note or note.user_id != current_user.id:
        abort(404)
    return render_template("note_detail.html", note=note)


@main_bp.route("/notas/<int:note_id>/excluir", methods=["POST"])
@login_required
def note_delete(note_id):
    note = db.session.get(BrokerageNote, note_id)
    if not note or note.user_id != current_user.id:
        abort(404)
    db.session.delete(note)
    db.session.commit()
    flash("Nota excluída.", "success")
    return redirect(url_for("main.notes"))


@main_bp.route("/negocios")
@login_required
def trades():
    page = request.args.get("page", 1, type=int)
    pagination = (Trade.query.filter_by(user_id=current_user.id)
                  .order_by(Trade.trade_date.desc(), Trade.id.desc())
                  .paginate(page=page, per_page=current_app.config["ITEMS_PER_PAGE"],
                            error_out=False))
    return render_template("trades.html", pagination=pagination)


# --- Lançamento manual (útil sem PDF) ---
@main_bp.route("/notas/manual", methods=["GET", "POST"])
@login_required
def note_manual():
    if request.method == "POST":
        try:
            td = datetime.strptime(request.form["trade_date"], "%Y-%m-%d").date()
            qty = Decimal(request.form["quantity"].replace(",", "."))
            price = Decimal(request.form["price"].replace(",", "."))
            corretagem = Decimal((request.form.get("corretagem") or "0").replace(",", ".") or "0")
        except (KeyError, ValueError, InvalidOperation):
            flash("Preencha data, quantidade e preço corretamente.", "error")
            return redirect(request.url)

        if qty <= 0 or price < 0:
            flash("Quantidade deve ser positiva e preço não pode ser negativo.", "error")
            return redirect(request.url)

        note = BrokerageNote(
            user_id=current_user.id, broker="MANUAL", trade_date=td, source="MANUAL",
            corretagem=corretagem,
            net_value=qty * price,
        )
        db.session.add(note)
        db.session.flush()
        db.session.add(Trade(
            user_id=current_user.id, note_id=note.id, trade_date=td,
            asset=request.form["asset"].upper().strip(),
            market=request.form.get("market", "VISTA"),
            side=request.form.get("side", "C"),
            quantity=qty, price=price, gross_value=qty * price,
        ))
        db.session.commit()
        flash("Negócio lançado manualmente.", "success")
        return redirect(url_for("main.trades"))
    return render_template("note_manual.html", hoje=date.today().isoformat())


# --------------------------------------------------------------------------- #
# Apuração mensal
# --------------------------------------------------------------------------- #
@main_bp.route("/apuracao")
@login_required
def apuracao():
    result = tax_engine.compute(_user_notes())
    months = list(reversed(result.months))   # mais recentes primeiro
    return render_template(
        "apuracao.html", months=months, result=result,
        darf_codigo=tax_engine.DARF_CODIGO, darf_min=tax_engine.DARF_MINIMO,
    )


# --------------------------------------------------------------------------- #
# Posições em aberto
# --------------------------------------------------------------------------- #
@main_bp.route("/posicoes")
@login_required
def positions():
    result = tax_engine.compute(_user_notes())
    total = sum((p.market_cost for p in result.positions), Decimal("0"))
    return render_template("positions.html", positions=result.positions, total=total)


# --------------------------------------------------------------------------- #
# Integração B3 (stub)
# --------------------------------------------------------------------------- #
@main_bp.route("/integracoes/b3", methods=["GET", "POST"])
@login_required
def b3_integration():
    cfg = B3Config.from_app_config(current_app.config)
    conn = B3Connection.query.filter_by(user_id=current_user.id).first()

    if request.method == "POST":
        if not cfg.enabled:
            flash("Integração com a B3 ainda não habilitada neste ambiente. "
                  "Defina B3_ENABLED=1 e as credenciais para ativar.", "warning")
        else:
            # Quando o OAuth estiver implementado, iniciar o fluxo aqui.
            flash("Fluxo de conexão B3 será iniciado (a implementar).", "info")
        return redirect(request.url)

    status = sync_status(conn, cfg)
    return render_template("integrations.html", status=status, cfg=cfg)
