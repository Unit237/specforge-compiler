"""
Engine base class + a tiny factory.

Every engine is a thin wrapper around a single "take these messages, return
text" call. No streaming, no function calling, no tools in v0.1 — the output
parser already gives us structure via `<file>` blocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class EngineError(RuntimeError):
    pass


@dataclass
class Call:
    model: str
    system: str
    user: str
    temperature: float
    max_output_tokens: int


class Engine(Protocol):
    name: str

    def run(self, call: Call) -> str:
        ...


def engine_for(name: str) -> "Engine":
    name = (name or "").lower()
    if name == "openai":
        from .openai_engine import OpenAIEngine
        return OpenAIEngine()
    if name == "anthropic":
        from .anthropic_engine import AnthropicEngine
        return AnthropicEngine()
    if name == "local":
        from .local_engine import LocalEngine
        return LocalEngine()
    if name == "custom":
        from .local_engine import CustomEngine
        return CustomEngine()
    raise EngineError(
        f"Unknown engine `{name}`. Valid: openai, anthropic, local, custom."
    )
