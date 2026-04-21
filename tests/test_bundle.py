from pathlib import Path

import pytest

from spec_compiler.bundle import BundleError, load_bundle


def _write_bundle(root: Path, extras: dict | None = None) -> None:
    (root / "spec.yaml").write_text(
        "schema: \"spec/v0.1\"\n"
        "name: demo\n"
        "spec:\n"
        "  entry: docs/product.md\n"
        "  include:\n"
        "    - \"docs/**/*.md\"\n"
        "prompts:\n"
        "  directory: prompts\n"
    )
    (root / "docs").mkdir()
    (root / "docs" / "product.md").write_text("# Product\n")
    (root / "docs" / "auth.md").write_text("# Auth\n")
    (root / "prompts").mkdir()
    (root / "prompts" / "scaffold.md").write_text("# Scaffold\n")


def test_load_bundle_orders_entry_first(tmp_path):
    _write_bundle(tmp_path)
    bundle = load_bundle(tmp_path)
    assert [s.rel for s in bundle.sources] == ["docs/product.md", "docs/auth.md"]
    assert [p.rel for p in bundle.prompts] == ["prompts/scaffold.md"]


def test_load_bundle_rejects_missing_md(tmp_path):
    (tmp_path / "spec.yaml").write_text(
        "schema: \"spec/v0.1\"\n"
        "name: demo\n"
        "spec:\n"
        "  entry: docs/nope.md\n"
        "  include: []\n"
    )
    with pytest.raises(BundleError):
        load_bundle(tmp_path)


def test_load_bundle_rejects_missing_manifest(tmp_path):
    with pytest.raises(BundleError):
        load_bundle(tmp_path)
