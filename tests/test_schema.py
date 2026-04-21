import pytest

from spec_compiler.schema import Route, SchemaError, parse_manifest


_MIN = {
    "schema": "spec/v0.1",
    "name": "demo",
    "spec": {"entry": "docs/product.md", "include": ["docs/**/*.md"]},
}


def test_minimum_manifest_parses():
    m = parse_manifest(_MIN)
    assert m.name == "demo"
    assert m.spec.entry == "docs/product.md"
    # Default engine is anthropic — matches the Claude-Code-first flow the
    # CLI uses and the compiler's dependency `extras`.
    assert m.compiler.engine == "anthropic"
    assert m.compiler.model == "claude-sonnet-4-5"
    assert m.output.target == "./out"


def test_missing_schema_rejected():
    with pytest.raises(SchemaError) as e:
        parse_manifest({"name": "x", "spec": {"entry": "a.md"}})
    assert "schema" in str(e.value)


def test_wrong_schema_rejected():
    with pytest.raises(SchemaError):
        parse_manifest({**_MIN, "schema": "spec/v9.9"})


def test_unknown_engine_rejected():
    with pytest.raises(SchemaError):
        parse_manifest({**_MIN, "compiler": {"engine": "carrier-pigeon"}})


def test_unknown_commit_style_rejected():
    with pytest.raises(SchemaError):
        parse_manifest({**_MIN, "output": {"commit_style": "rambling"}})


def test_routes_parsed():
    m = parse_manifest(
        {
            **_MIN,
            "compiler": {
                "routes": [
                    {"match": "docs/**/*.md", "model": "gpt-5-mini"},
                    {
                        "match": "prompts/**/*.md",
                        "engine": "anthropic",
                        "model": "claude-sonnet-4",
                        "temperature": 0.1,
                    },
                ]
            },
        }
    )
    assert len(m.compiler.routes) == 2
    assert m.compiler.routes[0] == Route(match="docs/**/*.md", model="gpt-5-mini")
    assert m.compiler.routes[1].engine == "anthropic"
    assert m.compiler.routes[1].temperature == 0.1


def test_route_missing_match_rejected():
    with pytest.raises(SchemaError) as e:
        parse_manifest({**_MIN, "compiler": {"routes": [{"model": "gpt-5"}]}})
    assert "match" in str(e.value)


def test_route_requires_an_override():
    with pytest.raises(SchemaError):
        parse_manifest({**_MIN, "compiler": {"routes": [{"match": "docs/**/*.md"}]}})


def test_route_unknown_key_rejected():
    with pytest.raises(SchemaError) as e:
        parse_manifest(
            {
                **_MIN,
                "compiler": {
                    "routes": [{"match": "x", "modeel": "typo"}]
                },
            }
        )
    assert "modeel" in str(e.value) or "unknown" in str(e.value).lower()


def test_route_unknown_engine_rejected():
    with pytest.raises(SchemaError):
        parse_manifest(
            {
                **_MIN,
                "compiler": {
                    "routes": [{"match": "x", "engine": "carrier-pigeon"}]
                },
            }
        )
