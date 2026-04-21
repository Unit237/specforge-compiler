import pytest

from spec_compiler.routing import group_by_config, resolve
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


# ---------------------------------------------------------------------------
# Tier 3: defaults
# ---------------------------------------------------------------------------


def test_defaults_when_no_routes_or_frontmatter():
    m = _manifest()
    r = resolve("docs/anything.md", m)
    assert r.config.engine == "openai"
    assert r.config.model == "gpt-5"
    assert len(r.trail) == 1
    assert r.trail[0].tier == "default"


# ---------------------------------------------------------------------------
# Tier 2: routes
# ---------------------------------------------------------------------------


def test_route_matches_and_overrides():
    m = _manifest(
        routes=[
            {"match": "docs/architecture/**/*.md", "model": "gpt-5", "temperature": 0.15},
            {"match": "docs/**/*.md", "model": "gpt-5-mini"},
        ]
    )
    r = resolve("docs/architecture/overview.md", m)
    assert r.config.model == "gpt-5"
    assert r.config.temperature == 0.15
    assert r.trail[-1].source == "route:docs/architecture/**/*.md"


def test_first_match_wins():
    m = _manifest(
        routes=[
            {"match": "docs/**/*.md", "model": "gpt-5-mini"},
            {"match": "docs/architecture/**/*.md", "model": "gpt-5"},
        ]
    )
    r = resolve("docs/architecture/overview.md", m)
    assert r.config.model == "gpt-5-mini"  # first match won, even though second is more specific


def test_route_partial_override_inherits_rest():
    m = _manifest(
        temperature=0.2,
        routes=[{"match": "prompts/**/*.md", "engine": "anthropic", "model": "claude-sonnet-4"}],
    )
    r = resolve("prompts/scaffold.md", m)
    assert r.config.engine == "anthropic"
    assert r.config.model == "claude-sonnet-4"
    assert r.config.temperature == 0.2  # inherited from defaults


def test_no_route_falls_through_to_default():
    m = _manifest(routes=[{"match": "prompts/**/*.md", "model": "claude-sonnet-4"}])
    r = resolve("docs/random.md", m)
    assert r.config.model == "gpt-5"


# ---------------------------------------------------------------------------
# Tier 1: frontmatter
# ---------------------------------------------------------------------------


def test_frontmatter_beats_route_and_defaults():
    m = _manifest(routes=[{"match": "docs/**/*.md", "model": "gpt-5-mini"}])
    r = resolve("docs/secret.md", m, frontmatter={"model": "gpt-5", "temperature": 0.05})
    assert r.config.model == "gpt-5"
    assert r.config.temperature == 0.05
    assert r.trail[-1].tier == "frontmatter"


def test_summary_mentions_source():
    m = _manifest(routes=[{"match": "docs/**/*.md", "model": "gpt-5-mini"}])
    r = resolve("docs/a.md", m)
    assert "gpt-5-mini" in r.summary
    assert "docs/**/*.md" in r.summary

    r2 = resolve("other.md", m)
    assert "gpt-5" in r2.summary
    assert "from" not in r2.summary  # defaults don't advertise source


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def test_grouping_merges_same_config():
    m = _manifest(routes=[{"match": "docs/**/*.md", "model": "gpt-5-mini"}])
    rs = [
        resolve("docs/a.md", m),
        resolve("docs/b.md", m),
        resolve("other.md", m),
    ]
    groups = group_by_config(rs)
    assert len(groups) == 2
    (cfg1, members1), (cfg2, members2) = groups
    assert cfg1.model == "gpt-5-mini"
    assert {m.path for m in members1} == {"docs/a.md", "docs/b.md"}
    assert cfg2.model == "gpt-5"
    assert {m.path for m in members2} == {"other.md"}
