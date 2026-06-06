"""Diário de trades: anotações em texto rico (Quill), com tags, vínculo a ativo,
busca e autosave. O HTML é sanitizado antes de salvar (as notas são privadas por
usuário, mas sanitizamos mesmo assim por higiene)."""
from datetime import UTC, datetime, timedelta

import bleach
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .extensions import db
from .models import Note
from .services import ai_insights

journal_bp = Blueprint("journal", __name__)

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
    result = ai_insights.analyze_note(note.title, note.tags, note.asset, body_text,
                                      strategy=current_user.strategy)
    return jsonify(result)


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


@journal_bp.route("/coach")
@login_required
def coach():
    return render_template("coach.html", strategy=current_user.strategy or "",
                           ai_enabled=ai_insights.is_enabled())


@journal_bp.route("/coach/estrategia", methods=["POST"])
@login_required
def coach_strategy():
    current_user.strategy = (request.form.get("strategy") or "").strip()[:8000]
    db.session.commit()
    flash("Estratégia salva.", "success")
    return redirect(url_for("journal.coach"))


@journal_bp.route("/coach/checklist", methods=["POST"])
@login_required
def coach_checklist():
    plan = (request.get_json(silent=True) or {}).get("plan", "")
    return jsonify(ai_insights.pre_trade_checklist(current_user.strategy, plan))


@journal_bp.route("/coach/chat", methods=["POST"])
@login_required
def coach_chat():
    question = (request.get_json(silent=True) or {}).get("question", "")
    return jsonify(ai_insights.chat(current_user.strategy, _notes_text(15), question))


@journal_bp.route("/coach/resumo", methods=["POST"])
@login_required
def coach_summary():
    return jsonify(ai_insights.weekly_summary(current_user.strategy,
                                              _notes_text(30, days=14)))


@journal_bp.route("/diario/<int:note_id>", methods=["POST"])
@login_required
def save_note(note_id):
    note = _owned(note_id)
    data = request.get_json(silent=True) or {}
    note.title = (data.get("title") or "").strip()[:200]
    note.body = sanitize_html(data.get("body") or "")
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
