"""Anthropic engine — uses the official `anthropic` SDK if installed."""

from __future__ import annotations

import os

from .base import Call, EngineError


class AnthropicEngine:
    name = "anthropic"

    def run(self, call: Call) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise EngineError(
                "The Anthropic engine needs the `anthropic` package. Install with:\n"
                "    pip install 'spec-compiler[anthropic]'"
            ) from e

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EngineError("ANTHROPIC_API_KEY is not set.")

        client = anthropic.Anthropic(api_key=api_key)
        try:
            resp = client.messages.create(
                model=call.model,
                max_tokens=call.max_output_tokens,
                temperature=call.temperature,
                system=call.system,
                messages=[{"role": "user", "content": call.user}],
            )
        except Exception as e:
            raise EngineError(f"Anthropic request failed: {e}") from e

        parts = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts).strip()
