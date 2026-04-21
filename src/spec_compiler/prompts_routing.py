"""
Per-session LLM resolution for ``.prompts`` files.

A ``.prompts`` file is one commit's worth of conversational history. Every
``[[sessions]]`` block inside it optionally carries a ``model`` field that
records which LLM produced that session. When we compile, we want to route
each session to a call configured with the same model it was authored
against — otherwise we're mixing reasoning traces across engines and the
output is noise.

The resolution precedence mirrors ``routing.resolve``:

    session.model  >  route-on-prompts-path  >  compiler defaults

A session with no ``model`` is considered "portable" — it's included as
context in every compile group. Sessions with a model land only in the
group whose resolved config matches that model.

We deliberately do NOT import the CLI's prompt-schema package — the
compiler has no runtime dep on the CLI. This module parses the minimum
it needs (``schema`` version, ``[[sessions]]`` ``id`` and ``model``) and
keeps the raw session text for re-embedding into the assembled prompt.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib as _tomllib
else:  # pragma: no cover - exercised on 3.9/3.10
    import tomli as _tomllib

from .bundle import SourceFile
from .routing import Resolution, ResolvedConfig, resolve
from .schema import Manifest


_PROMPTS_SCHEMA: str = "spec.prompts/v0.1"


class PromptsFileError(ValueError):
    """Raised when a ``.prompts`` file can't be parsed enough to route it."""


@dataclass(frozen=True)
class SessionRef:
    """A single ``[[sessions]]`` block, distilled down to what routing needs."""

    prompts_path: str          # e.g. "prompts/2026-04-21T16-00-00Z.prompts"
    session_id: str
    model: str | None
    title: str | None
    source: str | None
    raw_body: str              # the rendered text we'll embed at compile time


@dataclass
class SessionResolution:
    ref: SessionRef
    config: ResolvedConfig
    """Why this session landed on ``config``: "default" | "route" | "session.model"."""
    source: str


def parse_sessions(src: SourceFile) -> list[SessionRef]:
    """
    Extract every ``[[sessions]]`` block from a ``.prompts`` file.

    Non-fatal: a broken ``.prompts`` file doesn't kill the compile. We emit
    a single degraded SessionRef (``session_id="<unparseable>"``, model
    ``None``) so the file still ships as portable context — same shape the
    pipeline had before per-session routing existed. The CLI's
    ``spec prompts validate`` is the right place to get a precise
    error; the compiler's job is to not silently drop files.
    """
    try:
        data = _tomllib.loads(src.raw)
    except Exception:
        return [
            SessionRef(
                prompts_path=src.rel,
                session_id="<unparseable>",
                model=None,
                title=None,
                source=None,
                raw_body=src.raw,
            )
        ]

    if not isinstance(data, dict):
        return []

    schema = data.get("schema")
    if schema is not None and schema != _PROMPTS_SCHEMA:
        # Not fatal — future-schema files still parse as TOML, so we can
        # route them by `model` if they happen to have one. Just don't
        # promise validation.
        pass

    sessions_raw: Any = data.get("sessions") or []
    if not isinstance(sessions_raw, list):
        return []

    refs: list[SessionRef] = []
    for s in sessions_raw:
        if not isinstance(s, dict):
            continue
        sid = s.get("id")
        if not isinstance(sid, str) or not sid.strip():
            continue
        model = s.get("model")
        model = model if isinstance(model, str) and model.strip() else None
        title = s.get("title") if isinstance(s.get("title"), str) else None
        source = s.get("source") if isinstance(s.get("source"), str) else None
        refs.append(
            SessionRef(
                prompts_path=src.rel,
                session_id=sid,
                model=model,
                title=title,
                source=source,
                raw_body=src.raw,
            )
        )
    return refs


def resolve_session(ref: SessionRef, manifest: Manifest) -> SessionResolution:
    """
    Resolve a compiler config for a single session.

    Precedence (highest first):
        1. ``session.model`` from the ``.prompts`` file
        2. Any ``compiler.routes`` entry matching the prompts file path
        3. Compiler defaults
    """
    # Start from a path-based resolution (routes + defaults).
    base: Resolution = resolve(ref.prompts_path, manifest)

    if ref.model:
        # Session-level override — wins over routes and defaults.
        cfg = ResolvedConfig(
            engine=base.config.engine,
            model=ref.model,
            temperature=base.config.temperature,
            max_output_tokens=base.config.max_output_tokens,
        )
        return SessionResolution(ref=ref, config=cfg, source="session.model")

    if len(base.trail) > 1:
        return SessionResolution(ref=ref, config=base.config, source=base.trail[-1].source)
    return SessionResolution(ref=ref, config=base.config, source="default")


def gather_sessions(
    prompts: list[SourceFile], manifest: Manifest
) -> list[SessionResolution]:
    """Flatten every ``.prompts`` file into a list of resolved sessions."""
    out: list[SessionResolution] = []
    for p in prompts:
        for ref in parse_sessions(p):
            out.append(resolve_session(ref, manifest))
    return out


def sessions_for_config(
    all_sessions: list[SessionResolution], config: ResolvedConfig
) -> list[SessionResolution]:
    """
    Pick the sessions that should ride along with an LLM call configured
    as ``config``. Rule:

    - A session with no ``session.model`` (portable) rides with every call.
      It's ambient history.
    - A session with a pinned ``session.model`` rides only when the target
      engine+model match. The engine comparison is lenient: we match on
      ``model`` alone, because a session authored on ``claude-sonnet-4-6``
      is meaningful to any call that targets ``claude-sonnet-4-6``
      regardless of which SDK (anthropic vs. a proxy) is calling it.
    """
    out: list[SessionResolution] = []
    for s in all_sessions:
        if s.ref.model is None:
            out.append(s)
        elif s.config.model == config.model:
            out.append(s)
    return out


__all__ = [
    "PromptsFileError",
    "SessionRef",
    "SessionResolution",
    "parse_sessions",
    "resolve_session",
    "gather_sessions",
    "sessions_for_config",
]
