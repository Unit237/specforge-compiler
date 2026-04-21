"""
Local / custom engines.

`local`  — POSTs to a local OpenAI-compatible endpoint (Ollama, LM Studio,
           llama.cpp server). Reads `OPENAI_API_BASE` and uses the model name
           verbatim.

`custom` — POSTs the `Call` as JSON to `SPEC_CUSTOM_ENGINE_URL`, expects
           `{"text": "..."}` back. The escape hatch for self-hosted or
           home-grown engines; nothing about Spec requires OpenAI.
"""

from __future__ import annotations

import os

import requests

from .base import Call, EngineError


DEFAULT_LOCAL_BASE = "http://localhost:11434/v1"  # Ollama default


class LocalEngine:
    name = "local"

    def run(self, call: Call) -> str:
        base = os.environ.get("OPENAI_API_BASE", DEFAULT_LOCAL_BASE).rstrip("/")
        url = f"{base}/chat/completions"
        try:
            r = requests.post(
                url,
                json={
                    "model": call.model,
                    "temperature": call.temperature,
                    "max_tokens": call.max_output_tokens,
                    "messages": [
                        {"role": "system", "content": call.system},
                        {"role": "user", "content": call.user},
                    ],
                },
                headers={
                    "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', 'sk-local')}",
                    "Content-Type": "application/json",
                },
                timeout=600,
            )
        except requests.RequestException as e:
            raise EngineError(f"Local engine request failed ({url}): {e}") from e

        if r.status_code >= 400:
            raise EngineError(f"Local engine {url} → {r.status_code}: {r.text}")
        data = r.json()
        try:
            return (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError) as e:
            raise EngineError(f"Local engine returned an unexpected shape: {data!r}") from e


class CustomEngine:
    name = "custom"

    def run(self, call: Call) -> str:
        url = os.environ.get("SPEC_CUSTOM_ENGINE_URL")
        if not url:
            raise EngineError(
                "SPEC_CUSTOM_ENGINE_URL is not set. Point it at an endpoint "
                "that accepts {model, system, user, temperature, max_output_tokens} "
                "and returns {\"text\": \"...\"}."
            )
        try:
            r = requests.post(
                url,
                json={
                    "model": call.model,
                    "system": call.system,
                    "user": call.user,
                    "temperature": call.temperature,
                    "max_output_tokens": call.max_output_tokens,
                },
                timeout=600,
            )
        except requests.RequestException as e:
            raise EngineError(f"Custom engine request failed: {e}") from e

        if r.status_code >= 400:
            raise EngineError(f"Custom engine {url} → {r.status_code}: {r.text}")
        data = r.json()
        if not isinstance(data, dict) or "text" not in data:
            raise EngineError(f"Custom engine must return {{'text': ...}}; got {data!r}")
        return (data["text"] or "").strip()
