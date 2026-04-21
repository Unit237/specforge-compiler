import pytest

from spec_compiler.frontmatter import FrontmatterError, parse


def test_no_frontmatter_passthrough():
    text = "# Just a doc\n\nHello.\n"
    p = parse(text)
    assert p.body == text
    assert p.spec == {}
    assert p.extra == {}
    assert p.has_frontmatter is False


def test_spec_frontmatter_parsed():
    text = """---
spec:
  model: gpt-5
  temperature: 0.1
---
# Doc

Body.
"""
    p = parse(text)
    assert p.spec == {"model": "gpt-5", "temperature": 0.1}
    assert p.body.startswith("# Doc")
    assert "---" not in p.body


def test_non_spec_frontmatter_is_preserved_as_extra():
    text = """---
title: My Doc
tags: [a, b]
---
body
"""
    p = parse(text)
    assert p.spec == {}
    assert p.extra == {"title": "My Doc", "tags": ["a", "b"]}
    assert p.body == "body\n"


def test_unknown_spec_key_rejected():
    text = """---
spec:
  wat: true
---
body
"""
    with pytest.raises(FrontmatterError):
        parse(text, origin="docs/x.md")


def test_invalid_yaml_rejected():
    text = """---
:: not yaml ::
---
body
"""
    with pytest.raises(FrontmatterError):
        parse(text, origin="docs/x.md")
