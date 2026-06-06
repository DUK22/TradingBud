"""Insights com IA para o diário/coach de trades (API da Anthropic / Claude).

Opcional: só funciona quando ANTHROPIC_API_KEY está definida. Funções:
  - analyze_note  : revisa uma anotação (resumo, pontos fortes, alertas, dica)
  - pre_trade_checklist : valida um plano de operação contra a estratégia
  - chat          : responde perguntas usando as anotações do diário
  - weekly_summary: resume os últimos dias do diário

Tudo em português, com a ESTRATÉGIA do trader como contexto. Nunca dá
recomendação de compra/venda — é apoio educacional ao processo.
"""
from __future__ import annotations

import json
import logging

from flask import current_app

log = logging.getLogger(__name__)

BASE_SYSTEM = (
    "Você é um mentor de trading que ajuda um trader pessoa física brasileiro "
    "(renda variável: ações, day trade, mini-contratos) a melhorar disciplina, "
    "gestão de risco e processo. Responda em português do Brasil, objetivo e "
    "prático. NUNCA recomende comprar/vender um ativo nem prometa retorno; foque "
    "em método, regras e gestão de risco. Quando faltar informação, diga o que "
    "registrar da próxima vez."
)


def is_enabled() -> bool:
    return bool(current_app.config.get("ANTHROPIC_API_KEY"))


def _strategy_block(strategy: str | None) -> str:
    s = (strategy or "").strip()
    return f"\n\nESTRATÉGIA DO TRADER (use como referência):\n{s[:3000]}" if s else ""


def _client():
    import anthropic
    key = current_app.config.get("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=key) if key else None


def _handle_errors(fn):
    import anthropic
    try:
        return fn()
    except anthropic.AuthenticationError:
        return {"ok": False, "error": "Chave da IA inválida. Verifique ANTHROPIC_API_KEY."}
    except anthropic.RateLimitError:
        return {"ok": False, "error": "Limite da IA atingido. Tente novamente em instantes."}
    except anthropic.APIConnectionError:
        return {"ok": False, "error": "Sem conexão com o serviço de IA."}
    except anthropic.APIStatusError as e:
        log.warning("IA APIStatusError %s", e.status_code)
        return {"ok": False, "error": "O serviço de IA recusou a requisição."}
    except Exception:  # noqa: BLE001
        log.exception("Falha inesperada na IA")
        return {"ok": False, "error": "Falha ao processar. Tente novamente."}


def _call_json(system: str, user: str, schema: dict, max_tokens: int = 1024) -> dict:
    client = _client()
    if client is None:
        return {"ok": False, "error": "Recurso de IA não configurado."}

    def run():
        resp = client.messages.create(
            model=current_app.config.get("ANTHROPIC_MODEL", "claude-opus-4-8"),
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return {"ok": True, "data": json.loads(text)}

    return _handle_errors(run)


def _call_text(system: str, user: str, max_tokens: int = 1024) -> dict:
    client = _client()
    if client is None:
        return {"ok": False, "error": "Recurso de IA não configurado."}

    def run():
        resp = client.messages.create(
            model=current_app.config.get("ANTHROPIC_MODEL", "claude-opus-4-8"),
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return {"ok": True, "text": text.strip()}

    return _handle_errors(run)


_NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "resumo": {"type": "string"},
        "pontos_fortes": {"type": "array", "items": {"type": "string"}},
        "alertas": {"type": "array", "items": {"type": "string"}},
        "dica": {"type": "string"},
    },
    "required": ["resumo", "pontos_fortes", "alertas", "dica"],
    "additionalProperties": False,
}

_CHECKLIST_SCHEMA = {
    "type": "object",
    "properties": {
        "itens": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "criterio": {"type": "string"},
                "atende": {"type": "boolean"},
                "comentario": {"type": "string"},
            },
            "required": ["criterio", "atende", "comentario"],
            "additionalProperties": False,
        }},
        "veredito": {"type": "string"},
    },
    "required": ["itens", "veredito"],
    "additionalProperties": False,
}


def analyze_note(title, tags, asset, body_text, strategy=None) -> dict:
    if not (body_text or "").strip():
        return {"ok": False, "error": "Escreva algo na anotação antes de analisar."}
    system = BASE_SYSTEM + _strategy_block(strategy)
    user = (f"Título: {title or '(sem título)'}\nAtivo: {asset or '(não informado)'}\n"
            f"Tags: {tags or '(nenhuma)'}\n\nAnotação:\n{body_text.strip()[:6000]}")
    r = _call_json(system, user, _NOTE_SCHEMA)
    return {"ok": True, "analysis": r["data"]} if r.get("ok") else r


def pre_trade_checklist(strategy, plan_text) -> dict:
    if not (plan_text or "").strip():
        return {"ok": False, "error": "Descreva a operação que pretende fazer."}
    system = (BASE_SYSTEM + _strategy_block(strategy) +
              "\n\nValide o PLANO de operação abaixo contra a estratégia. Para cada "
              "critério relevante (entrada, stop, alvo, risco/retorno, tamanho, "
              "horário, contexto), diga se o plano atende e comente. Termine com um "
              "veredito curto. Não diga se o trade vai dar certo; avalie só o processo.")
    user = f"Plano de operação:\n{plan_text.strip()[:3000]}"
    r = _call_json(system, user, _CHECKLIST_SCHEMA)
    return {"ok": True, "analysis": r["data"]} if r.get("ok") else r


def chat(strategy, notes_context, question) -> dict:
    if not (question or "").strip():
        return {"ok": False, "error": "Escreva uma pergunta."}
    system = (BASE_SYSTEM + _strategy_block(strategy) +
              "\n\nResponda à pergunta do trader usando as anotações do diário dele "
              "abaixo como evidência. Seja específico e cite padrões que observar. Se "
              "as anotações não tiverem a resposta, diga isso.")
    user = (f"ANOTAÇÕES DO DIÁRIO (mais recentes):\n{(notes_context or '(vazio)')[:8000]}"
            f"\n\nPERGUNTA: {question.strip()[:500]}")
    return _call_text(system, user, max_tokens=1024)


def weekly_summary(strategy, notes_text) -> dict:
    if not (notes_text or "").strip():
        return {"ok": False, "error": "Sem anotações no período para resumir."}
    system = (BASE_SYSTEM + _strategy_block(strategy) +
              "\n\nResuma o período do diário abaixo: principais acertos, erros "
              "recorrentes, disciplina em relação à estratégia e 1-3 focos para a "
              "próxima semana. Use tópicos curtos.")
    user = f"ANOTAÇÕES DO PERÍODO:\n{notes_text[:8000]}"
    return _call_text(system, user, max_tokens=1024)
