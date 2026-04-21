"""The compiler's bundle loader must refuse to read files out of the
`curated/_pending/` review-staging area. A pending prompt has not been
approved by a human reviewer yet; letting it through to compilation would
defeat the whole purpose of the review gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spec_compiler.bundle import load_bundle


PROMPT_BODY = (
    'schema = "spec.prompts/v0.1"\n'
    "[commit]\n"
    'branch = "main"\n'
    'author_name = "Test"\n'
    'author_email = "test@example.com"\n'
    "\n"
    "[[sessions]]\n"
    'id = "{sid}"\n'
    'source = "manual"\n'
    "\n"
    "  [[sessions.turns]]\n"
    '  role = "user"\n'
    '  text = "hi"\n'
)


def _write_bundle(root: Path) -> None:
    (root / "spec.yaml").write_text(
        'schema: "spec/v0.1"\n'
        "name: tiered\n"
        "spec:\n"
        "  entry: docs/product.md\n"
        "  include:\n"
        '    - "docs/**/*.md"\n'
        "prompts:\n"
        "  directory: prompts\n"
    )
    (root / "docs").mkdir()
    (root / "docs" / "product.md").write_text("# Product\n")

    (root / "prompts" / "captured").mkdir(parents=True)
    (root / "prompts" / "captured" / "cap.prompts").write_text(
        PROMPT_BODY.format(sid="cap")
    )
    (root / "prompts" / "curated").mkdir(parents=True)
    (root / "prompts" / "curated" / "cur.prompts").write_text(
        PROMPT_BODY.format(sid="cur")
    )
    (root / "prompts" / "curated" / "_pending").mkdir(parents=True)
    (root / "prompts" / "curated" / "_pending" / "pend.prompts").write_text(
        PROMPT_BODY.format(sid="pend")
    )


def test_bundle_loader_excludes_pending(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    bundle = load_bundle(tmp_path)

    rels = {p.rel for p in bundle.prompts}
    assert "prompts/captured/cap.prompts" in rels
    assert "prompts/curated/cur.prompts" in rels
    # The pending prompt must NOT be in the compile input.
    assert "prompts/curated/_pending/pend.prompts" not in rels
    assert not any("_pending" in r for r in rels)


def test_bundle_loader_includes_legacy_root_files(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    (tmp_path / "prompts" / "legacy.prompts").write_text(PROMPT_BODY.format(sid="leg"))
    bundle = load_bundle(tmp_path)
    rels = {p.rel for p in bundle.prompts}
    assert "prompts/legacy.prompts" in rels
