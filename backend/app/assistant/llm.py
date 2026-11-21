"""Clientul LLM abstractizat. Producția folosește Claude API; testele, un client fals.

Mesajele au formatul Messages API: {"role": "user"|"assistant", "content": str | [blocuri]}.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import get_settings

API_URL = "https://api.anthropic.com/v1/messages"


class LLMNotConfigured(Exception):
    """Lipsește cheia API: asistentul nu poate răspunde."""


class LLMError(Exception):
    """Serviciul LLM a refuzat sau n-a răspuns."""


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMReply: ...


class AnthropicClient:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMReply:
        body = {"model": self.model, "max_tokens": 1500, "system": system, "messages": messages, "tools": tools}
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        try:
            resp = httpx.post(API_URL, json=body, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError("Serviciul AI nu a răspuns. Încercați din nou.") from exc
        reply = LLMReply()
        try:
            for block in data.get("content", []):
                if block.get("type") == "text":
                    reply.text += block.get("text", "")
                elif block.get("type") == "tool_use":
                    reply.tool_calls.append(ToolCall(block["id"], block["name"], block.get("input") or {}))
        except (KeyError, AttributeError, TypeError) as exc:
            raise LLMError("Răspuns neașteptat de la serviciul AI.") from exc
        return reply


def get_llm_client() -> LLMClient:
    """Dependență FastAPI (suprascrisă în teste cu un client fals)."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise LLMNotConfigured
    return AnthropicClient(settings.anthropic_api_key, settings.ai_model)
