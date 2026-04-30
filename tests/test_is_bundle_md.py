"""
Truth-table tests for the compiler's mirror of `is_bundle_md`.

Mirrors `spec-cli/tests/test_is_bundle_md.py` — the two implementations
must agree for every input or `spec compile` and `spec status` will
disagree about which `.md` files are bundle content. When you change a
case in either file, change it in both.
"""

from __future__ import annotations

import pytest

from spec_compiler.constants import (
    AGENT_INSTRUCTION_FILENAMES,
    AGENT_INSTRUCTION_PATTERNS,
    DEFAULT_SPEC_INCLUDE,
    HUMAN_DOC_FILENAMES,
    is_bundle_md,
)


def test_constants_in_agreement_with_cli():
    # If these drift the CLI and compiler will disagree about which
    # `.md` is bundle content. Pin the values explicitly.
    assert "agents.md" in AGENT_INSTRUCTION_FILENAMES
    assert "claude.md" in AGENT_INSTRUCTION_FILENAMES
    assert "llms.txt" in AGENT_INSTRUCTION_FILENAMES
    assert "readme.md" in HUMAN_DOC_FILENAMES
    assert "changelog.md" in HUMAN_DOC_FILENAMES
    assert ".github/copilot-instructions.md" in AGENT_INSTRUCTION_PATTERNS
    assert DEFAULT_SPEC_INCLUDE == ("docs/**/*.md",)


def test_default_include_glob():
    assert is_bundle_md("docs/product.md")
    assert is_bundle_md("docs/architecture/billing.md")
    assert not is_bundle_md("README.md")
    assert not is_bundle_md("notes/scratch.md")


def test_agent_allowlist_at_any_depth():
    assert is_bundle_md("AGENTS.md")
    assert is_bundle_md("backend/app/CLAUDE.md")
    assert is_bundle_md("agents.md")
    assert is_bundle_md(".github/copilot-instructions.md")


def test_human_denylist_under_docs_excluded_by_default():
    # `docs/CHANGELOG.md` would match the default include glob, but
    # the denylist beats the default. Same as the CLI side.
    assert not is_bundle_md("docs/CHANGELOG.md")
    assert not is_bundle_md("docs/README.md")


def test_explicit_include_beats_denylist():
    spec = {"include": ["docs/README.md", "docs/**/*.md"]}
    assert is_bundle_md("docs/README.md", manifest_spec=spec)


def test_exclude_beats_default_include():
    spec = {"include": ["docs/**/*.md"], "exclude": ["docs/internal/**/*.md"]}
    assert is_bundle_md("docs/product.md", manifest_spec=spec)
    assert not is_bundle_md("docs/internal/scratch.md", manifest_spec=spec)


def test_frontmatter_overrides():
    assert is_bundle_md("PLAN.md", frontmatter={"spec": True})
    assert not is_bundle_md("docs/product.md", frontmatter={"spec": False})
    assert is_bundle_md("PLAN.md", frontmatter={"spec": {"include": True}})


def test_non_md_returns_false():
    assert not is_bundle_md("logo.png")
    assert not is_bundle_md("src/app.py")
    assert not is_bundle_md("prompts/foo.prompts")
    assert not is_bundle_md("spec.yaml")


@pytest.mark.parametrize(
    "rel,expected",
    [
        ("docs/product.md", True),
        ("AGENTS.md", True),
        ("README.md", False),
        ("LICENSE", False),
        ("docs/README.md", False),
        ("notes/scratch.md", False),
    ],
)
def test_no_manifest_no_frontmatter(rel, expected):
    assert is_bundle_md(rel) == expected
