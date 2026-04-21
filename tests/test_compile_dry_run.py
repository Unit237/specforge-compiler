from pathlib import Path

from spec_compiler.compile import CompileOptions, compile_bundle


def test_dry_run_end_to_end(tmp_path):
    (tmp_path / "spec.yaml").write_text(
        "schema: \"spec/v0.1\"\n"
        "name: demo\n"
        "spec:\n"
        "  entry: docs/product.md\n"
        "  include:\n"
        "    - \"docs/**/*.md\"\n"
        "compiler:\n"
        "  engine: openai\n"
        "  model: gpt-5\n"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "product.md").write_text("# Product\n\nHello.\n")

    result = compile_bundle(tmp_path, CompileOptions(dry_run=True))
    assert result.dry_run is True
    assert result.files == []
    assert result.config_hash  # deterministic, non-empty
    # config hash is stable across repeated runs
    again = compile_bundle(tmp_path, CompileOptions(dry_run=True))
    assert again.config_hash == result.config_hash
