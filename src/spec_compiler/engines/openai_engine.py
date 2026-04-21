"""OpenAI engine — uses the official `openai` SDK if installed."""

from __future__ import annotations

import os

from .base import Call, EngineError


class OpenAIEngine:
    name = "openai"

    def run(self, call: Call) -> str:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise EngineError(
                "The OpenAI engine needs the `openai` package. Install with:\n"
                "    pip install 'spec-compiler[openai]'"
            ) from e

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EngineError(
                "OPENAI_API_KEY is not set. Export it in your shell before running "
                "`spec compile`. The compiler never reads credentials from Cloud."
            )

        client = OpenAI(api_key=api_key)
        try:
            resp = client.chat.completions.create(
                model=call.model,
                temperature=call.temperature,
                max_tokens=call.max_output_tokens,
                messages=[
                    {"role": "system", "content": call.system},
                    {"role": "user", "content": call.user},
                ],
            )
        except Exception as e:  # SDK raises a handful of different types
            raise EngineError(f"OpenAI request failed: {e}") from e

        choice = resp.choices[0]
        return (choice.message.content or "").strip()
