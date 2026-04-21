"""Per-session LLM routing for `.prompts` files."""

from __future__ import annotations

from spec_compiler.bundle import SourceFile
from spec_compiler.prompts_routing import (
    gather_sessions,
    parse_sessions,
    resolve_session,
    sessions_for_config,
)
from spec_compiler.routing import ResolvedConfig, resolve
from spec_compiler.schema import parse_manifest


_BASE = {
    "schema": "spec/v0.1",
    "name": "demo",
    "spec": {"entry": "docs/product.md", "include": ["docs/**/*.md"]},
}


def _manifest(routes=None, **compiler_overrides):
    compiler = {
        "engine": "openai",
        "model": "gpt-5",
        "temperature": 0.2,
        "max_output_tokens": 8000,
        **compiler_overrides,
    }
    if routes is not None:
        compiler["routes"] = routes
    return parse_manifest({**_BASE, "compiler": compiler})


def _prompts_src(rel: str, raw: str) -> SourceFile:
    return SourceFile(rel=rel, abs_path=None, content=raw, raw=raw)  # type: ignore[arg-type]


_TWO_SESSIONS = """\
schema = "spec.prompts/v0.1"

[commit]
branch = "main"
author_name = "Alice"
author_email = "alice@example.com"

[[sessions]]
id = "s1"
source = "claude_code"
model = "claude-opus-4-1"
title = "Architecture"

  [[sessions.turns]]
  role = "user"
  text = "design the module"

[[sessions]]
id = "s2"
source = "cursor"
model = "gpt-5-mini"
title = "Sketch"

  [[sessions.turns]]
  role = "user"
  text = "try a quick sketch"

[[sessions]]
id = "s3"
source = "manual"
title = "Plain text notes (portable)"

  [[sessions.turns]]
  role = "user"
  text = "notes"
"""


def test_parse_sessions_extracts_model_and_id():
    src = _prompts_src("prompts/a.prompts", _TWO_SESSIONS)
    refs = parse_sessions(src)
    assert [r.session_id for r in refs] == ["s1", "s2", "s3"]
    assert refs[0].model == "claude-opus-4-1"
    assert refs[1].model == "gpt-5-mini"
    assert refs[2].model is None


def test_session_model_beats_route_and_defaults():
    m = _manifest(routes=[{"match": "prompts/**/*.prompts", "model": "gpt-5-mini"}])
    src = _prompts_src("prompts/a.prompts", _TWO_SESSIONS)
    sessions = [resolve_session(r, m) for r in parse_sessions(src)]
    assert sessions[0].config.model == "claude-opus-4-1"  # session.model wins
    assert sessions[0].source == "session.model"
    # s3 has no session.model → falls through to the route.
    assert sessions[2].config.model == "gpt-5-mini"
    assert "prompts/**" in sessions[2].source


def test_sessions_for_config_includes_portables_and_matching_models():
    m = _manifest()
    src = _prompts_src("prompts/a.prompts", _TWO_SESSIONS)
    all_sessions = gather_sessions([src], m)

    cfg_opus = ResolvedConfig(
        engine="anthropic",
        model="claude-opus-4-1",
        temperature=0.2,
        max_output_tokens=8000,
    )
    opus = sessions_for_config(all_sessions, cfg_opus)
    assert [s.ref.session_id for s in opus] == ["s1", "s3"]

    cfg_mini = ResolvedConfig(
        engine="openai",
        model="gpt-5-mini",
        temperature=0.2,
        max_output_tokens=8000,
    )
    mini = sessions_for_config(all_sessions, cfg_mini)
    assert [s.ref.session_id for s in mini] == ["s2", "s3"]


def test_unparseable_prompts_file_is_kept_as_portable_context():
    src = _prompts_src("prompts/bad.prompts", "not valid [[ toml")
    refs = parse_sessions(src)
    assert len(refs) == 1
    assert refs[0].session_id == "<unparseable>"
    assert refs[0].model is None  # rides with every call
