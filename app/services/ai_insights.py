"""Insights com IA para o diário de trades (API da Anthropic / Claude).

Opcional: só funciona quando ANTHROPIC_API_KEY está definida. Recebe o texto de
uma anotação e devolve uma análise estruturada (resumo, pontos fortes, alertas,
dica) em português. Usa saída estruturada (JSON schema) e cache do system prompt.
"""
from __future__ import annotations

import json
import logging

from flask import current_app

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Você é um mentor de trading que revisa anotações do diário de um trader "
    "pessoa física brasileiro (renda variável: ações, day trade, mini-contratos). "
    "Analise a anotação e responda em português do Brasil, de forma objetiva, "
    "prática e encorajadora. Foque em disciplina, gestão de risco e processo — "
    "não em achismo de mercado. NUNCA dê recomendação de compra/venda nem promessa "
    "de retorno. Se faltar informação, aponte o que registrar da próxima vez."
)

# Saída estruturada: garante JSON válido com os 4 campos.
_SCHEMA = {
    "type": "object",
    "properties": {
        "resumo": {"type": "string", "description": "1-2 frases resumindo a anotação"},
        "pontos_fortes": {"type": "array", "items": {"type": "string"}},
        "alertas": {"type": "array", "items": {"type": "string"},
                    "description": "erros, riscos ou vieses a evitar"},
        "dica": {"type": "string", "description": "uma dica acionável para a próxima operação"},
    },
    "required": ["resumo", "pontos_fortes", "alertas", "dica"],
    "additionalProperties": False,
}


def is_enabled() -> bool:
    return bool(current_app.config.get("ANTHROPIC_API_KEY"))


def analyze_note(title: str, tags: str, asset: str, body_text: str) -> dict:
    """Retorna {"ok": True, "analysis": {...}} ou {"ok": False, "error": "..."}."""
    import anthropic  # import tardio: dependência só usada quando a IA é chamada

    key = current_app.config.get("ANTHROPIC_API_KEY")
    if not key:
        return {"ok": False, "error": "Recurso de IA não configurado."}
    if not (body_text or "").strip():
        return {"ok": False, "error": "Escreva algo na anotação antes de analisar."}

    model = current_app.config.get("ANTHROPIC_MODEL", "claude-opus-4-8")
    client = anthropic.Anthropic(api_key=key)
    user_content = (
        f"Título: {title or '(sem título)'}\n"
        f"Ativo: {asset or '(não informado)'}\n"
        f"Tags: {tags or '(nenhuma)'}\n\n"
        f"Anotação:\n{body_text.strip()[:6000]}"
    )
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            system=[{
                "type": "text", "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # cacheia o prompt estável
            }],
            messages=[{"role": "user", "content": user_content}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return {"ok": True, "analysis": json.loads(text)}
    except anthropic.AuthenticationError:
        return {"ok": False, "error": "Chave da IA inválida. Verifique ANTHROPIC_API_KEY."}
    except anthropic.RateLimitError:
        return {"ok": False, "error": "Limite da IA atingido. Tente novamente em instantes."}
    except anthropic.APIConnectionError:
        return {"ok": False, "error": "Sem conexão com o serviço de IA."}
    except anthropic.APIStatusError as e:
        log.warning("IA APIStatusError %s: %s", e.status_code, getattr(e, "message", ""))
        return {"ok": False, "error": "O serviço de IA recusou a requisição."}
    except Exception:  # noqa: BLE001
        log.exception("Falha inesperada na análise de IA")
        return {"ok": False, "error": "Falha ao analisar. Tente novamente."}
