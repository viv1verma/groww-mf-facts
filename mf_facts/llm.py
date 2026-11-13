"""Minimal client for any OpenAI-compatible chat-completions API.

Google Gemini and Groq both offer free tiers behind this same request format,
so switching provider is a configuration change, not a code change:

    LLM_PROVIDER = gemini | groq | custom
    LLM_API_KEY  = your key
    LLM_MODEL    = optional override of the provider's default model
    LLM_BASE_URL = required only for LLM_PROVIDER=custom

Free-tier model names and limits change often. If the default model below is
retired, set LLM_MODEL to a current one from your provider's console.

Privacy note: on some free tiers the provider may use prompts to improve its
products. We only send the user's question and passages from public scheme
documents, and questions containing personal data are blocked before this point.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .net import urlopen

PROVIDERS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        # Checked against Google's model list on 2026-11-13. gemini-2.5-flash
        # is closed to new users. If Google is busy (HTTP 503) the client
        # tries the fallbacks in order.
        "model": "gemini-3.5-flash",
        "fallbacks": ("gemini-3.5-flash-lite", "gemini-flash-lite-latest"),
        # Newer Gemini models "think" before answering. Low effort keeps
        # replies fast. The thinking tokens count toward max_tokens.
        "extra": {"reasoning_effort": "low"},
        "key_env": "GEMINI_API_KEY",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "fallbacks": (),
        "extra": {},
        "key_env": "GROQ_API_KEY",
    },
}

# Errors worth retrying on another model: overloaded, rate-limited,
# model retired, or a timeout. Anything else (e.g. a bad key) is not retried.
_RETRY_STATUS = {404, 429, 500, 502, 503, 504}


class LLMError(Exception):
    """The LLM could not be reached or returned something unusable."""


@dataclass
class LLMConfig:
    provider: str
    base_url: str
    model: str
    api_key: str
    fallbacks: tuple = ()
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "LLMConfig | None":
        provider = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
        preset = PROVIDERS.get(provider, {})
        api_key = os.environ.get("LLM_API_KEY") or os.environ.get(preset.get("key_env", ""), "")
        base_url = os.environ.get("LLM_BASE_URL") or preset.get("base_url", "")
        model = os.environ.get("LLM_MODEL") or preset.get("model", "")
        if not (api_key and base_url and model):
            return None
        fallbacks = tuple(
            m.strip() for m in os.environ.get("LLM_FALLBACK_MODELS", "").split(",") if m.strip()
        ) or tuple(preset.get("fallbacks", ()))
        return cls(
            provider, base_url.rstrip("/"), model, api_key,
            fallbacks=tuple(m for m in fallbacks if m != model),
            extra=dict(preset.get("extra", {})),
        )


class ChatClient:
    # 3 attempts × 15 s stays inside Vercel's 60 s function limit.
    def __init__(self, config: LLMConfig, timeout: float = 15.0):
        self.config = config
        self.timeout = timeout

    def complete_json(self, system: str, user: str, max_tokens: int = 2000) -> dict:
        """Send the request, trying fallback models if the provider is busy."""
        last: LLMError | None = None
        for model in (self.config.model, *self.config.fallbacks):
            try:
                return self._complete(model, system, user, max_tokens)
            except _Retryable as exc:
                print(f"[mf-facts] {model} unavailable ({exc}); trying next model")
                last = LLMError(str(exc))
        raise last or LLMError("No model available")

    def _complete(self, model: str, system: str, user: str, max_tokens: int) -> dict:
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            **self.config.extra,
        }
        request = urllib.request.Request(
            f"{self.config.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            # The error body is not passed on to the user because it can
            # contain account details.
            if exc.code in _RETRY_STATUS:
                raise _Retryable(f"HTTP {exc.code}") from exc
            raise LLMError(f"LLM HTTP {exc.code}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError):
                raise _Retryable("timeout") from exc
            raise LLMError(f"LLM request failed: {type(exc).__name__}") from exc
        except json.JSONDecodeError as exc:
            raise LLMError("LLM returned a non-JSON HTTP body") from exc

        try:
            content = payload["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LLMError("LLM response had no message content") from exc
        if not content.strip():
            # Thinking models can use the whole budget and return nothing.
            raise _Retryable("empty reply")
        return parse_json_object(content)


class _Retryable(Exception):
    pass


def parse_json_object(content: str) -> dict:
    """Parse a JSON object, tolerating ```json fences some models add."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("LLM did not return a JSON object")
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError("LLM returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise LLMError("LLM did not return a JSON object")
    return value


def get_client() -> ChatClient | None:
    config = LLMConfig.from_env()
    return ChatClient(config) if config else None
