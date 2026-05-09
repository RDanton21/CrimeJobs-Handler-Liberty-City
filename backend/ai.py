from __future__ import annotations

from typing import Protocol

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from .config import settings
from .prompts import SYSTEM_PROMPT


class AIProvider(Protocol):
    name: str
    async def generate(self, user_prompt: str, model: str | None = None) -> str: ...


class ClaudeProvider:
    name = "anthropic"

    def __init__(self, api_key: str, default_model: str):
        self._client = AsyncAnthropic(api_key=api_key) if api_key else None
        self._default_model = default_model

    async def generate(self, user_prompt: str, model: str | None = None) -> str:
        if not self._client:
            raise RuntimeError("Anthropic API-Key nicht gesetzt.")
        resp = await self._client.messages.create(
            model=model or self._default_model,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        chunks: list[str] = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                chunks.append(block.text)
        return "".join(chunks).strip()


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, default_model: str):
        self._client = AsyncOpenAI(api_key=api_key) if api_key else None
        self._default_model = default_model

    async def generate(self, user_prompt: str, model: str | None = None) -> str:
        if not self._client:
            raise RuntimeError("OpenAI API-Key nicht gesetzt.")
        resp = await self._client.chat.completions.create(
            model=model or self._default_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=600,
            temperature=0.85,
        )
        return (resp.choices[0].message.content or "").strip()


async def get_provider(
    provider: str,
    keys: dict[str, str],
    models: dict[str, str],
) -> AIProvider:
    p = (provider or settings.default_ai_provider).lower()
    if p == "anthropic":
        return ClaudeProvider(
            api_key=keys.get("anthropic", "") or settings.anthropic_api_key,
            default_model=models.get("claude") or settings.default_claude_model,
        )
    if p == "openai":
        return OpenAIProvider(
            api_key=keys.get("openai", "") or settings.openai_api_key,
            default_model=models.get("openai") or settings.default_openai_model,
        )
    raise ValueError(f"Unbekannter Provider: {provider}")
