"""Blueprint principal: dashboard, upload/OCR, notas, apuração, posições, B3."""
import json
import os
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, logout_user
from werkzeug.utils import secure_filename

from .extensions import db
from .models import B3Connection, BrokerageNote, Note, PositionAdjustment, Trade, User
from .services import b3_import, contracts, darf_pdf, fees, ocr, tax_engine
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
    _remove_provisional(user.id, {note.trade_date})   # nota oficial substitui a provisória
    return note


def _remove_provisional(user_id, dates) -> int:
    """Remove notas provisórias do usuário nas datas informadas (reconciliação)."""
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


def _user_notes():
    return (BrokerageNote.query
            .filter_by(user_id=current_user.id)
            .order_by(BrokerageNote.trade_date.asc())
            .all())


def _user_adjustments():
    return (PositionAdjustment.query
            .filter_by(user_id=current_user.id)
            .order_by(PositionAdjustment.event_date.asc())
            .all())


def _compute_user():
    """Apuração completa do usuário (notas + eventos corporativos)."""
    return tax_engine.compute(_user_notes(), adjustments=_user_adjustments())


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@main_bp.route("/")
@login_required
def dashboard():
    notes = _user_notes()
    result = tax_engine.compute(notes, adjustments=_user_adjustments())

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

    asset_results = defaultdict(Decimal)
    for r in result.day_results:
        asset_results[r.asset] += r.net_result
    for s in result.swing_sales:
        asset_results[s.asset] += s.result
    top_assets = sorted(asset_results.items(), key=lambda item: abs(item[1]), reverse=True)[:8]
    chart["asset_labels"] = [asset for asset, _ in top_assets]
    chart["asset_results"] = [float(value) for _, value in top_assets]

    # Métricas de performance (cada fechamento = um day trade ou uma venda swing)
    closed = ([r.net_result for r in result.day_results]
              + [s.result for s in result.swing_sales])
    n_ops = len(closed)
    wins = sum(1 for x in closed if x > 0)
    win_vals = [x for x in closed if x > 0]
    loss_vals = [x for x in closed if x < 0]
    gross_profit = sum(win_vals, Decimal("0"))
    gross_loss = -sum(loss_vals, Decimal("0"))
    metrics = {
        "n_ops": n_ops,
        "wins": wins,
        "win_rate": (Decimal(wins) / n_ops * 100) if n_ops else Decimal("0"),
        "melhor": max(closed) if closed else Decimal("0"),
        "pior": min(closed) if closed else Decimal("0"),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else None,
        "avg_win": (gross_profit / len(win_vals)) if win_vals else Decimal("0"),
        "avg_loss": (gross_loss / len(loss_vals)) if loss_vals else Decimal("0"),
        "expectancy": (sum(closed, Decimal("0")) / n_ops) if n_ops else Decimal("0"),
    }
    # Curva de capital por operação fechada (ordem cronológica)
    ops_sorted = sorted(
        [(r.trade_date, float(r.net_result)) for r in result.day_results]
        + [(s.trade_date, float(s.result)) for s in result.swing_sales])
    eq_acc, eq_series, eq_labels = 0.0, [], []
    for d, v in ops_sorted:
        eq_acc += v
        eq_series.append(round(eq_acc, 2))
        eq_labels.append(d.strftime("%d/%m/%y"))
    chart["eq"] = eq_series
    chart["eq_labels"] = eq_labels
    # Isenção mensal de R$20k (vendas à vista de ações no swing, mês corrente)
    isencao = {
        "usado": cur.equity_swing_gross if cur else Decimal("0"),
        "limite": tax_engine.ISENCAO_SWING_MENSAL,
    }

    return render_template(
        "dashboard.html",
        result=result, cur=cur, patrimonio=patrimonio,
        resultado_ano=resultado_ano, imposto_ano=imposto_ano,
        ano=ano, chart=chart, n_notas=len(notes),
        metrics=metrics, isencao=isencao,
    )


# --------------------------------------------------------------------------- #
# Mercado — gráfico em tempo real (widget TradingView)
# --------------------------------------------------------------------------- #
@main_bp.route("/mercado")
@login_required
def market():
    symbol = (request.args.get("symbol") or "").upper().strip() or "BMFBOVESPA:PETR4"
    # Ativos em carteira viram atalhos rápidos (prefixo da bolsa para o widget).
    result = _compute_user()
    carteira = [("BMFBOVESPA:" + p.asset, p.asset) for p in result.positions]
    favoritos = [
        ("BMFBOVESPA:IBOV", "IBOV"), ("BMFBOVESPA:PETR4", "PETR4"),
        ("BMFBOVESPA:VALE3", "VALE3"), ("BMFBOVESPA:ITUB4", "ITUB4"),
        ("BMFBOVESPA:WIN1!", "WIN (mini índice)"),
        ("BMFBOVESPA:WDO1!", "WDO (mini dólar)"),
        ("AMEX:EWZ", "EWZ (Brasil em NY)"),
    ]
    # Tickers conhecidos fora da B3 (digitados sem prefixo de bolsa)
    _known_us = {"EWZ": "AMEX:EWZ", "QQQ": "NASDAQ:QQQ", "SPY": "AMEX:SPY"}
    if symbol in _known_us:
        symbol = _known_us[symbol]
    # Para as calculadoras (valor do ponto) e posição no ativo atual.
    point_values = {k: float(v) for k, v in contracts.POINT_VALUES.items()}
    asset_atual = symbol.split(":")[-1]
    pos_atual = next((p for p in result.positions if p.asset == asset_atual), None)
    notas_ativo = (Note.query.filter_by(user_id=current_user.id, asset=asset_atual)
                   .order_by(Note.updated_at.desc()).limit(5).all())
    return render_template(
        "market.html", symbol=symbol, carteira=carteira, favoritos=favoritos,
        point_values=point_values, pos_atual=pos_atual, asset_atual=asset_atual,
        notas_ativo=notas_ativo, saved_layout=current_user.layout_mercado or "null")


@main_bp.route("/mercado/layout", methods=["POST"])
@login_required
def market_layout():
    """Salva (na conta) o layout da página Mercado — sincroniza entre dispositivos."""
    data = request.get_json(silent=True)
    if not isinstance(data, list) or len(data) > 40:
        return jsonify({"ok": False, "error": "formato inválido"}), 400
    clean = []
    for it in data:
        if not isinstance(it, dict):
            continue
        try:
            clean.append({
                "id": str(it.get("id", ""))[:40],
                "type": str(it.get("type", ""))[:40],
                "x": int(it.get("x", 0)), "y": int(it.get("y", 0)),
                "w": int(it.get("w", 1)), "h": int(it.get("h", 1)),
            })
        except (TypeError, ValueError):
            continue
    current_user.layout_mercado = json.dumps(clean)
    db.session.commit()
    return jsonify({"ok": True})


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


@main_bp.route("/notas/provisoria", methods=["GET", "POST"])
@login_required
def note_provisional():
    """Nota provisória do dia: lança vários negócios, estima custos e marca como
    provisória. Substituída automaticamente quando a nota oficial é importada."""
    if request.method == "POST":
        try:
            td = datetime.strptime(request.form["trade_date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            flash("Informe a data do pregão.", "error")
            return redirect(request.url)

        assets = request.form.getlist("asset")
        markets = request.form.getlist("market")
        sides = request.form.getlist("side")
        qtys = request.form.getlist("quantity")
        prices = request.form.getlist("price")

        parsed_trades, volume = [], Decimal("0")
        for i, asset in enumerate(assets):
            asset = (asset or "").upper().strip()
            if not asset:
                continue
            try:
                qty = Decimal((qtys[i] or "0").replace(",", "."))
                price = Decimal((prices[i] or "0").replace(",", "."))
            except (IndexError, InvalidOperation):
                continue
            if qty <= 0 or price < 0:
                continue
            gross = qty * price
            volume += gross
            parsed_trades.append((asset, (markets[i] if i < len(markets) else "VISTA"),
                                  (sides[i] if i < len(sides) else "C"), qty, price, gross))

        if not parsed_trades:
            flash("Adicione pelo menos um negócio válido.", "error")
            return redirect(request.url)

        custo = fees.estimate_costs(volume)
        note = BrokerageNote(
            user_id=current_user.id, broker="PROVISÓRIA", trade_date=td, source="MANUAL",
            provisional=True, emolumentos=custo, net_value=volume)
        db.session.add(note)
        db.session.flush()
        for asset, market, side, qty, price, gross in parsed_trades:
            db.session.add(Trade(
                user_id=current_user.id, note_id=note.id, trade_date=td, asset=asset,
                market=market, side=side, quantity=qty, price=price, gross_value=gross))
        db.session.commit()
        flash(f"Nota provisória criada ({len(parsed_trades)} negócio[s], custo estimado "
              f"{custo}). Será substituída ao importar a oficial.", "success")
        return redirect(url_for("main.apuracao"))
    return render_template("note_provisional.html", hoje=date.today().isoformat())


# --------------------------------------------------------------------------- #
# Apuração mensal
# --------------------------------------------------------------------------- #
@main_bp.route("/apuracao")
@login_required
def apuracao():
    result = _compute_user()
    months = list(reversed(result.months))   # mais recentes primeiro
    return render_template(
        "apuracao.html", months=months, result=result,
        darf_codigo=tax_engine.DARF_CODIGO, darf_min=tax_engine.DARF_MINIMO,
    )


@main_bp.route("/apuracao/<int:year>/<int:month>/darf.pdf")
@login_required
def darf_pdf_download(year, month):
    """DARF (demonstrativo) em PDF para o mês informado."""
    result = _compute_user()
    m = result.month(year, month)
    if not m:
        abort(404)
    pdf_bytes = darf_pdf.build(current_user, m)
    resp = Response(pdf_bytes, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = (
        f"inline; filename=darf-{year}-{month:02d}.pdf")
    return resp



# --------------------------------------------------------------------------- #
# Eventos corporativos (desdobramento / grupamento / bonificação)
# --------------------------------------------------------------------------- #
@main_bp.route("/ajustes", methods=["GET", "POST"])
@login_required
def adjustments():
    if request.method == "POST":
        asset = (request.form.get("asset") or "").strip().upper()
        kind = (request.form.get("kind") or "").strip().upper()
        event_date = None
        try:
            event_date = datetime.strptime(
                request.form.get("event_date", ""), "%Y-%m-%d").date()
        except ValueError:
            pass

        def dec(name):
            raw = (request.form.get(name) or "").strip().replace(",", ".")
            if not raw:
                return None
            try:
                return Decimal(raw)
            except InvalidOperation:
                return None

        factor, qty, price = dec("factor"), dec("qty"), dec("price")
        errors = []
        if not asset:
            errors.append("Informe o ativo.")
        if kind not in PositionAdjustment.KINDS:
            errors.append("Tipo de evento inválido.")
        if not event_date:
            errors.append("Informe a data do evento.")
        if kind in ("DESDOBRAMENTO", "GRUPAMENTO") and (not factor or factor <= 0):
            errors.append("Informe o fator (novas por antigas), ex.: 10 ou 0,1.")
        if kind == "BONIFICACAO" and (not qty or qty <= 0):
            errors.append("Informe a quantidade de ações recebidas.")
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            db.session.add(PositionAdjustment(
                user_id=current_user.id, asset=asset, event_date=event_date,
                kind=kind, factor=factor, qty=qty,
                price=price if price is not None else Decimal("0"),
                note=(request.form.get("note") or "").strip()[:255]))
            db.session.commit()
            flash("Evento registrado. A apuração e as posições já o consideram.", "success")
            return redirect(url_for("main.adjustments"))

    items = (PositionAdjustment.query.filter_by(user_id=current_user.id)
             .order_by(PositionAdjustment.event_date.desc()).all())
    return render_template("adjustments.html", items=items,
                           kinds=PositionAdjustment.KINDS)


@main_bp.route("/ajustes/<int:adj_id>/excluir", methods=["POST"])
@login_required
def delete_adjustment(adj_id):
    adj = db.session.get(PositionAdjustment, adj_id)
    if not adj or adj.user_id != current_user.id:
        abort(404)
    db.session.delete(adj)
    db.session.commit()
    flash("Evento removido.", "success")
    return redirect(url_for("main.adjustments"))


# --------------------------------------------------------------------------- #
# PWA (instalável no celular) — manifest, service worker e página offline
# --------------------------------------------------------------------------- #
@main_bp.route("/manifest.webmanifest")
def manifest():
    data = {
        "name": "IR Traders — TradingBud",
        "short_name": "TradingBud",
        "description": "Apuração de IR e diário de trades para renda variável.",
        "start_url": "/", "scope": "/", "display": "standalone",
        "background_color": "#0b0f14", "theme_color": "#0b0f14", "lang": "pt-BR",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return Response(json.dumps(data), mimetype="application/manifest+json")


_SERVICE_WORKER = """
const CACHE = 'tradingbud-v1';
const ASSETS = ['/static/app.css', '/static/icons/icon-192.png', '/offline'];
self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) =>
    Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
  ).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(caches.match(req).then((r) => r || fetch(req).then((resp) => {
      const cp = resp.clone(); caches.open(CACHE).then((c) => c.put(req, cp)); return resp;
    })));
    return;
  }
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(() => caches.match('/offline')));
  }
});
"""


@main_bp.route("/sw.js")
def service_worker():
    resp = Response(_SERVICE_WORKER, mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@main_bp.route("/offline")
def offline():
    return render_template("offline.html")


# --------------------------------------------------------------------------- #
# Posições em aberto
# --------------------------------------------------------------------------- #
@main_bp.route("/posicoes")
@login_required
def positions():
    result = _compute_user()
    total = sum((p.market_cost for p in result.positions), Decimal("0"))
    return render_template("positions.html", positions=result.positions, total=total)


@main_bp.route("/api/cotacoes")
@login_required
def api_quotes():
    """Cotações ao vivo (ações B3) para os tickers informados. JSON {ticker: preço}."""
    from .services import quotes
    raw = request.args.get("tickers", "")
    tickers = [t.strip().upper() for t in raw.split(",") if t.strip()][:30]
    return jsonify(quotes.get_prices(tickers))


# --------------------------------------------------------------------------- #
# Conta / LGPD (exportação e exclusão dos dados do usuário)
# --------------------------------------------------------------------------- #
@main_bp.route("/conta")
@login_required
def account():
    return render_template("account.html")


@main_bp.route("/conta/senha", methods=["POST"])
@login_required
def account_password():
    """Troca a senha do usuário logado."""
    atual = request.form.get("atual", "")
    nova = request.form.get("nova", "")
    confirma = request.form.get("confirma", "")
    if not current_user.check_password(atual):
        flash("Senha atual incorreta.", "error")
    elif len(nova) < 8:
        flash("A nova senha precisa ter ao menos 8 caracteres.", "error")
    elif nova != confirma:
        flash("A confirmação não confere com a nova senha.", "error")
    else:
        current_user.set_password(nova)
        db.session.commit()
        flash("Senha alterada com sucesso.", "success")
    return redirect(url_for("main.account"))


@main_bp.route("/conta/exemplo", methods=["POST"])
@login_required
def load_example_data():
    """Popula a conta com algumas notas/negócios de exemplo (para conhecer o app)."""
    y = date.today().year

    def add(d, trades, irrf_day=0, irrf_swing=0):
        note = BrokerageNote(user_id=current_user.id, broker="EXEMPLO", trade_date=d,
                             source="MANUAL", irrf_day=Decimal(str(irrf_day)),
                             irrf_swing=Decimal(str(irrf_swing)))
        db.session.add(note)
        db.session.flush()
        for asset, market, side, qty, price in trades:
            db.session.add(Trade(
                user_id=current_user.id, note_id=note.id, trade_date=d, asset=asset,
                market=market, side=side, quantity=Decimal(str(qty)),
                price=Decimal(str(price)), gross_value=Decimal(str(qty)) * Decimal(str(price))))

    add(date(y, 1, 8),  [("ITUB4", "VISTA", "C", 200, 30)])
    add(date(y, 1, 22), [("ITUB4", "VISTA", "V", 200, 33)], irrf_swing="0.33")
    add(date(y, 2, 10), [("PETR4", "VISTA", "C", 1000, 38)])
    add(date(y, 3, 10), [("PETR4", "VISTA", "C", 500, 39), ("PETR4", "VISTA", "V", 500, 39.8)], irrf_day="4")
    add(date(y, 3, 20), [("PETR4", "VISTA", "V", 1000, 41)], irrf_swing="2.05")
    db.session.commit()
    flash("Dados de exemplo carregados! Dá uma olhada no Dashboard e na Apuração.", "success")
    return redirect(url_for("main.dashboard"))


@main_bp.route("/conta/exportar")
@login_required
def account_export():
    """Exporta todos os dados do usuário em JSON (direito de portabilidade)."""
    notes = _user_notes()
    data = {
        "perfil": {
            "nome": current_user.name,
            "email": current_user.email,
            "cpf": current_user.cpf,
            "criado_em": current_user.created_at,
        },
        "notas": [{
            "id": n.id, "corretora": n.broker, "numero": n.note_number,
            "data_pregao": n.trade_date, "data_liquidacao": n.settlement_date,
            "segmento": n.segment, "origem": n.source,
            "corretagem": n.corretagem, "emolumentos": n.emolumentos,
            "taxa_liquidacao": n.taxa_liquidacao, "taxa_registro": n.taxa_registro,
            "iss": n.iss, "outras": n.outras,
            "irrf_day": n.irrf_day, "irrf_swing": n.irrf_swing,
            "net_value": n.net_value,
            "negocios": [{
                "data": t.trade_date, "ativo": t.asset, "mercado": t.market,
                "lado": t.side, "quantidade": t.quantity, "preco": t.price,
                "valor": t.gross_value,
            } for t in n.trades],
        } for n in notes],
    }
    payload = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    resp = Response(payload, mimetype="application/json")
    resp.headers["Content-Disposition"] = (
        f"attachment; filename=ir-traders-dados-{current_user.id}.json")
    return resp


@main_bp.route("/conta/excluir", methods=["POST"])
@login_required
def account_delete():
    """Exclui a conta e TODOS os dados (cascade remove notas/negócios/B3)."""
    user = db.session.get(User, current_user.id)
    logout_user()
    db.session.delete(user)
    db.session.commit()
    flash("Sua conta e todos os dados associados foram excluídos.", "success")
    return redirect(url_for("auth.login"))


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


@main_bp.route("/integracoes/b3/importar", methods=["POST"])
@login_required
def b3_import_upload():
    """Importa a planilha de Negociação da B3 (Extratos > Negociação)."""
    file = request.files.get("planilha")
    if not file or not file.filename:
        flash("Selecione a planilha exportada da B3.", "error")
        return redirect(url_for("main.b3_integration"))
    if not file.filename.lower().endswith((".xlsx", ".csv")):
        flash("Envie o arquivo .xlsx ou .csv exportado pela B3.", "error")
        return redirect(url_for("main.b3_integration"))

    try:
        parsed = b3_import.parse(file.stream, file.filename)
    except Exception as e:  # noqa: BLE001
        flash(f"Falha ao ler a planilha: {e}", "error")
        return redirect(url_for("main.b3_integration"))

    trades = parsed["trades"]
    if not trades:
        flash("Nenhuma operação importada. " + " ".join(parsed["warnings"]), "warning")
        return redirect(url_for("main.b3_integration"))

    # Agrupa por (corretora, dia) -> uma nota por dia.
    groups = defaultdict(list)
    for t in trades:
        groups[(t["broker"], t["trade_date"])].append(t)
    for (broker, d), ts in groups.items():
        note = BrokerageNote(user_id=current_user.id, broker=broker, trade_date=d, source="B3")
        db.session.add(note)
        db.session.flush()
        for t in ts:
            db.session.add(Trade(
                user_id=current_user.id, note_id=note.id, trade_date=d,
                asset=t["asset"], market=t["market"], side=t["side"],
                quantity=t["quantity"], price=t["price"], gross_value=t["gross_value"]))
    db.session.commit()
    _remove_provisional(current_user.id, {d for (_, d) in groups})  # substitui provisórias

    msg = f"Importação concluída: {len(trades)} negócio(s) em {len(groups)} dia(s)."
    if parsed["warnings"]:
        msg += " " + " ".join(parsed["warnings"])
    flash(msg + " Atenção: o extrato da B3 não traz custos/IRRF.", "success")
    return redirect(url_for("main.trades"))
