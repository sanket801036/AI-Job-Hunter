"""One function to get JSON out of an LLM, with fallback across providers.

Providers are tried in the order of AI_PROVIDERS. A provider is skipped when its key
is missing, and the next one is tried when a call fails, times out, is rate limited,
or returns something that is not valid JSON for the caller.
"""
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

TIMEOUT = 30

# Providers that failed in this process are tried last for the rest of the run, so one
# slow or rate-limited API does not cost a timeout on every job.
_recent_failures: set[str] = set()


class AllProvidersFailed(RuntimeError):
    pass


@dataclass
class Provider:
    name: str
    key: str
    call: Callable[[str, str, str], str]  # (key, system, user) -> raw text


def _gemini(model: str) -> Callable[[str, str, str], str]:
    def call(key: str, system: str, user: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }
        r = httpx.post(url, json=body, headers={"x-goog-api-key": key}, timeout=TIMEOUT)
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)

    return call


def _openai_compatible(base_url: str, model: str) -> Callable[[str, str, str], str]:
    """Mistral, Cerebras and Groq all speak the OpenAI chat format."""

    def call(key: str, system: str, user: str) -> str:
        body = {
            "model": model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        r = httpx.post(
            f"{base_url}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    return call


def build_providers(s: Settings) -> list[Provider]:
    known = {
        "gemini": Provider("gemini", s.gemini_api_key, _gemini(s.gemini_model)),
        "gemini2": Provider("gemini2", s.gemini_api_key_2, _gemini(s.gemini_model)),
        "mistral": Provider("mistral", s.mistral_api_key,
                            _openai_compatible("https://api.mistral.ai/v1", s.mistral_model)),
        "cerebras": Provider("cerebras", s.cerebras_api_key,
                             _openai_compatible("https://api.cerebras.ai/v1", s.cerebras_model)),
        "groq": Provider("groq", s.groq_api_key,
                         _openai_compatible("https://api.groq.com/openai/v1", s.groq_model)),
    }
    out = []
    for name in s.providers:
        p = known.get(name)
        if p is None:
            log.warning("unknown provider %r in AI_PROVIDERS, ignored", name)
        elif p.key:
            out.append(p)
    return out


def parse_json(raw: str) -> dict:
    """Models sometimes wrap JSON in ```json fences or add a sentence; pull the object out."""
    raw = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.S)
    if fenced:
        raw = fenced.group(1)
    else:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            raw = raw[start : end + 1]
    return json.loads(raw)


def complete_json(
    system: str,
    user: str,
    validate: Callable[[dict], Any] = lambda d: d,
    providers: list[Provider] | None = None,
) -> tuple[Any, str]:
    """Return (validated result, provider name). `validate` may raise to reject an
    answer, which moves on to the next provider."""
    providers = providers if providers is not None else build_providers(get_settings())
    if not providers:
        raise AllProvidersFailed("no LLM provider has an API key set")
    providers = sorted(providers, key=lambda p: p.name in _recent_failures)  # stable sort
    errors = []
    for p in providers:
        try:
            result = validate(parse_json(p.call(p.key, system, user)))
            _recent_failures.discard(p.name)
            return result, p.name
        except httpx.HTTPStatusError as e:
            msg = f"{p.name}: HTTP {e.response.status_code}"
        except Exception as e:  # timeout, bad JSON, failed validation, odd response shape
            msg = f"{p.name}: {type(e).__name__}: {str(e)[:200]}"
        log.warning("LLM fallback, %s", msg)
        _recent_failures.add(p.name)
        errors.append(msg)
    raise AllProvidersFailed("; ".join(errors))
