"""Diário de trades: anotações em texto rico (Quill), com tags, vínculo a ativo,
busca e autosave. O HTML é sanitizado antes de salvar (as notas são privadas por
usuário, mas sanitizamos mesmo assim por higiene).

Imagens coladas no editor chegam como data URI (base64). Ao salvar, elas são
EXTRAÍDAS para arquivos em UPLOAD_FOLDER/journal/<user_id>/ e o src é trocado
por uma rota autenticada — assim o banco não incha com blobs base64."""
import base64
import hashlib
import os
import re
from datetime import UTC, datetime, timedelta

import bleach
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required

from .extensions import db
from .models import BrokerageNote, Note, PositionAdjustment, StrategyProfile
from .services import ai_insights, tax_engine, trade_stats

_VISION_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def _uploaded_images(files, max_files=4, max_bytes=4_500_000):
    """Converte uploads (FileStorage) em blocos de imagem da API Claude."""
    blocks = []
    for f in (files or [])[:max_files]:
        if not f or not getattr(f, "filename", ""):
            continue
        raw = f.read(max_bytes + 1)
        if not raw or len(raw) > max_bytes:
            continue
        media = (f.mimetype or "").lower()
        if media == "image/jpg":
            media = "image/jpeg"
        if media not in _VISION_TYPES:
            continue
        blocks.append({"type": "image", "source": {
            "type": "base64", "media_type": media,
            "data": base64.b64encode(raw).decode()}})
    return blocks

journal_bp = Blueprint("journal", __name__)

_EXT_BY_MEDIA = {"image/png": "png", "image/jpeg": "jpg",
                 "image/gif": "gif", "image/webp": "webp"}
_MEDIA_BY_EXT = {v: k for k, v in _EXT_BY_MEDIA.items()}
_DATA_URI_SRC = re.compile(
    r'src="data:(image/(?:png|jpe?g|gif|webp));base64,([^"]+)"', re.IGNORECASE)
_IMG_NAME_RE = re.compile(r"^[0-9a-f]{16}\.(png|jpg|gif|webp)$")


def _journal_dir(user_id: int) -> str:
    d = os.path.join(current_app.config["UPLOAD_FOLDER"], "journal", str(user_id))
    os.makedirs(d, exist_ok=True)
    return d


def externalize_images(html: str, user_id: int, max_bytes: int = 8_000_000) -> str:
    """Move imagens base64 do HTML para arquivos; troca o src pela rota
    autenticada. Nome = hash do conteúdo (idempotente, deduplica)."""
    def repl(m):
        media = m.group(1).lower()
        if media == "image/jpg":
            media = "image/jpeg"
        try:
            raw = base64.b64decode(re.sub(r"\s+", "", m.group(2)), validate=True)
        except Exception:  # noqa: BLE001
            return m.group(0)
        if not raw or len(raw) > max_bytes:
            return m.group(0)
        name = hashlib.sha256(raw).hexdigest()[:16] + "." + _EXT_BY_MEDIA[media]
        path = os.path.join(_journal_dir(user_id), name)
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(raw)
        return 'src="' + url_for("journal.journal_image", filename=name) + '"'

    return _DATA_URI_SRC.sub(repl, html or "")


def stored_image_blocks(html: str, user_id: int,
                        max_images: int = 6, max_bytes: int = 4_500_000) -> list[dict]:
    """Blocos de imagem (API Claude) a partir dos arquivos referenciados no HTML."""
    blocks = []
    for m in re.finditer(r'src="[^"]*/diario/img/([0-9a-f]{16}\.\w{3,4})"', html or ""):
        name = m.group(1)
        if not _IMG_NAME_RE.match(name):
            continue
        path = os.path.join(_journal_dir(user_id), name)
        try:
            with open(path, "rb") as f:
                raw = f.read(max_bytes + 1)
        except OSError:
            continue
        if not (200 <= len(raw) <= max_bytes):
            continue
        media = _MEDIA_BY_EXT.get(name.rsplit(".", 1)[1])
        blocks.append({"type": "image", "source": {
            "type": "base64", "media_type": media,
            "data": base64.b64encode(raw).decode()}})
        if len(blocks) >= max_images:
            break
    return blocks


@journal_bp.route("/diario/img/<filename>")
@login_required
def journal_image(filename):
    """Serve a imagem do diário do PRÓPRIO usuário (não há acesso cruzado:
    o diretório é por user_id da sessão)."""
    if not _IMG_NAME_RE.match(filename):
        abort(404)
    return send_from_directory(_journal_dir(current_user.id), filename)

_ALLOWED_TAGS = [
    "p", "br", "hr", "h1", "h2", "h3", "strong", "b", "em", "i", "u", "s",
    "blockquote", "code", "pre", "ul", "ol", "li", "a", "img", "span", "sub", "sup",
]
_ALLOWED_ATTRS = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt"],
    "span": ["class"], "p": ["class"], "li": ["class", "data-list"], "ol": ["data-list"],
}
_ALLOWED_PROTOCOLS = ["http", "https", "mailto", "data"]


def sanitize_html(html: str) -> str:
    return bleach.clean(html or "", tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS,
                        protocols=_ALLOWED_PROTOCOLS, strip=True)


def text_preview(html: str, n: int = 160) -> str:
    txt = bleach.clean(html or "", tags=[], strip=True)
    txt = " ".join(txt.split())
    return (txt[:n] + "…") if len(txt) > n else txt


def _norm_tags(raw: str) -> str:
    seen = []
    for t in (raw or "").split(","):
        t = t.strip()
        if t and t.lower() not in [s.lower() for s in seen]:
            seen.append(t)
    return ",".join(seen[:20])[:255]


def _owned(note_id: int) -> Note:
    note = db.session.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        abort(404)
    return note


@journal_bp.route("/diario")
@login_required
def list_notes():
    q = request.args.get("q", "").strip()
    tag = request.args.get("tag", "").strip()
    asset = request.args.get("asset", "").strip().upper()
    query = Note.query.filter_by(user_id=current_user.id)
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Note.title.ilike(like), Note.body.ilike(like),
                                    Note.tags.ilike(like)))
    if tag:
        query = query.filter(Note.tags.ilike(f"%{tag}%"))
    if asset:
        query = query.filter(Note.asset == asset)
    page = request.args.get("page", 1, type=int)
    pagination = (query.order_by(Note.updated_at.desc())
                  .paginate(page=page, per_page=12, error_out=False))
    return render_template("journal_list.html", pagination=pagination,
                           q=q, tag=tag, asset=asset, preview=text_preview)


@journal_bp.route("/diario/novo")
@login_required
def new_note():
    asset = request.args.get("asset", "").strip().upper() or None
    note = Note(user_id=current_user.id, title="", body="", asset=asset)
    db.session.add(note)
    db.session.commit()
    return redirect(url_for("journal.edit_note", note_id=note.id))


@journal_bp.route("/diario/<int:note_id>")
@login_required
def edit_note(note_id):
    return render_template("journal_edit.html", note=_owned(note_id),
                           ai_enabled=ai_insights.is_enabled())


@journal_bp.route("/diario/<int:note_id>/analisar", methods=["POST"])
@login_required
def analyze_note(note_id):
    """Análise da anotação com IA (Claude). Devolve JSON estruturado."""
    note = _owned(note_id)
    body_text = bleach.clean(note.body or "", tags=[], strip=True)
    # imagens: arquivos externalizados + data URIs legados (notas antigas)
    images = (stored_image_blocks(note.body, current_user.id)
              + ai_insights.images_from_html(note.body))[:6]
    result = ai_insights.analyze_note(note.title, note.tags, note.asset, body_text,
                                      strategy=_active_strategy_text(), images=images)
    return jsonify(result)


@journal_bp.route("/diario/<int:note_id>/salvar-analise", methods=["POST"])
@login_required
def save_analysis(note_id):
    """Salva resultado da IA no histórico da nota."""
    note = _owned(note_id)
    data = request.get_json(silent=True) or {}

    analysis = {
        "timestamp": datetime.now(UTC).isoformat(),
        "resumo": data.get("resumo", ""),
        "pontos_fortes": data.get("pontos_fortes", []),
        "alertas": data.get("alertas", []),
        "dica": data.get("dica", ""),
        "saved_as": data.get("saved_as", "separate")  # "separate" ou "integrated"
    }

    if not note.analysis_history:
        note.analysis_history = []
    note.analysis_history.append(analysis)
    db.session.commit()

    return jsonify({"ok": True, "analysis": analysis})


# --------------------------------------------------------------------------- #
# Coach (estratégia + checklist + chat + resumo) — usa IA
# --------------------------------------------------------------------------- #
def _notes_text(limit=15, days=None) -> str:
    q = Note.query.filter_by(user_id=current_user.id)
    if days:
        since = datetime.now(UTC) - timedelta(days=days)
        q = q.filter(Note.updated_at >= since)
    out = []
    for n in q.order_by(Note.updated_at.desc()).limit(limit).all():
        txt = bleach.clean(n.body or "", tags=[], strip=True)
        out.append(f"[{n.updated_at:%d/%m} {n.asset or ''}] {n.title or 'Sem título'}: {txt[:600]}")
    return "\n".join(out)


def _strategies():
    return (StrategyProfile.query.filter_by(user_id=current_user.id)
            .order_by(StrategyProfile.updated_at.desc()).all())


def _owned_strategy(sid: int) -> StrategyProfile:
    sp = db.session.get(StrategyProfile, sid)
    if not sp or sp.user_id != current_user.id:
        abort(404)
    return sp


def _active_strategy():
    """Estratégia selecionada. Na 1ª vez migra a estratégia legada (User.strategy)."""
    sp = None
    if current_user.active_strategy_id:
        sp = db.session.get(StrategyProfile, current_user.active_strategy_id)
        if sp and sp.user_id != current_user.id:
            sp = None
    if sp is None:
        existing = _strategies()
        if existing:
            sp = existing[0]
        elif (current_user.strategy or "").strip():
            sp = StrategyProfile(user_id=current_user.id, name="Minha estratégia",
                                 content=current_user.strategy.strip())
            db.session.add(sp)
            db.session.flush()
        if sp and current_user.active_strategy_id != sp.id:
            current_user.active_strategy_id = sp.id
        db.session.commit()
    return sp


def _active_strategy_text() -> str:
    sp = _active_strategy()
    return sp.content if sp else ""


def _coach_stats():
    """Estatísticas dos negócios reais (sem IA) para o painel do Coach."""
    notes = (BrokerageNote.query.filter_by(user_id=current_user.id)
             .order_by(BrokerageNote.trade_date.asc()).all())
    adjustments = (PositionAdjustment.query.filter_by(user_id=current_user.id)
                   .order_by(PositionAdjustment.event_date.asc()).all())
    result = tax_engine.compute(notes, adjustments=adjustments)
    return trade_stats.compute_stats(result)


@journal_bp.route("/coach")
@login_required
def coach():
    return render_template("coach.html", strategies=_strategies(), stats=_coach_stats(),
                           active=_active_strategy(), ai_enabled=ai_insights.is_enabled())


@journal_bp.route("/coach/estrategia", methods=["POST"])
@login_required
def coach_strategy():
    sid = request.form.get("id", type=int)
    name = (request.form.get("name") or "").strip()[:120] or "Estratégia"
    content = (request.form.get("content") or request.form.get("strategy") or "").strip()[:8000]
    if sid:
        sp = _owned_strategy(sid)
        sp.name, sp.content = name, content
    else:
        sp = StrategyProfile(user_id=current_user.id, name=name, content=content)
        db.session.add(sp)
        db.session.flush()
    current_user.active_strategy_id = sp.id
    db.session.commit()
    flash("Estratégia salva.", "success")
    return redirect(url_for("journal.coach"))


@journal_bp.route("/coach/estrategia/<int:sid>/selecionar", methods=["POST"])
@login_required
def coach_strategy_select(sid):
    current_user.active_strategy_id = _owned_strategy(sid).id
    db.session.commit()
    return redirect(url_for("journal.coach"))


@journal_bp.route("/coach/estrategia/<int:sid>/excluir", methods=["POST"])
@login_required
def coach_strategy_delete(sid):
    sp = _owned_strategy(sid)
    was_active = current_user.active_strategy_id == sp.id
    db.session.delete(sp)
    db.session.flush()
    if was_active:
        others = _strategies()
        current_user.active_strategy_id = others[0].id if others else None
    db.session.commit()
    flash("Estratégia excluída.", "success")
    return redirect(url_for("journal.coach"))


@journal_bp.route("/coach/analisar-imagem", methods=["POST"])
@login_required
def coach_analyze_image():
    images = _uploaded_images(request.files.getlist("imagens")
                              or request.files.getlist("imagem"))
    if not images:
        return jsonify({"ok": False,
                        "error": "Anexe um print (PNG/JPG/WEBP) de até ~4 MB."})
    context = request.form.get("contexto", "")
    return jsonify(ai_insights.analyze_screenshot(_active_strategy_text(), images, context))


@journal_bp.route("/coach/checklist", methods=["POST"])
@login_required
def coach_checklist():
    plan = (request.get_json(silent=True) or {}).get("plan", "")
    return jsonify(ai_insights.pre_trade_checklist(_active_strategy_text(), plan))


@journal_bp.route("/coach/chat", methods=["POST"])
@login_required
def coach_chat():
    question = (request.get_json(silent=True) or {}).get("question", "")
    return jsonify(ai_insights.chat(_active_strategy_text(), _notes_text(15), question))


@journal_bp.route("/coach/resumo", methods=["POST"])
@login_required
def coach_summary():
    return jsonify(ai_insights.weekly_summary(_active_strategy_text(),
                                              _notes_text(30, days=14)))


@journal_bp.route("/diario/<int:note_id>", methods=["POST"])
@login_required
def save_note(note_id):
    note = _owned(note_id)
    data = request.get_json(silent=True) or {}
    note.title = (data.get("title") or "").strip()[:200]
    note.body = externalize_images(sanitize_html(data.get("body") or ""),
                                   current_user.id)
    note.tags = _norm_tags(data.get("tags") or "")
    note.asset = (data.get("asset") or "").strip().upper()[:20] or None
    db.session.commit()
    return jsonify({"ok": True})


@journal_bp.route("/diario/<int:note_id>/excluir", methods=["POST"])
@login_required
def delete_note(note_id):
    note = _owned(note_id)
    db.session.delete(note)
    db.session.commit()
    flash("Anotação excluída.", "success")
    return redirect(url_for("journal.list_notes"))
