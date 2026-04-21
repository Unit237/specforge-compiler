"""
Emit a small `CHANGELOG.md` delta next to the generated code.

Deliberately minimal — we append one entry per compile, dated, listing every
generated path. Real commit-style conformance is out of scope for v0.1; we
honor the `commit_style` setting only in the heading.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .output import GeneratedFile

if TYPE_CHECKING:
    from .bundle import Bundle


def write_changelog(
    target: Path,
    files: list[GeneratedFile],
    *,
    bundle: "Bundle",
    commit_style: str = "conventional",
) -> Path:
    path = target / "CHANGELOG.md"
    header_prefix = {
        "conventional": "chore(compile)",
        "plain": "compile",
        "none": "",
    }.get(commit_style, "chore(compile)")

    stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    header = f"## {stamp}"
    if header_prefix:
        header = f"{header}  {header_prefix}: {bundle.manifest.name}"

    lines = [header, ""]
    for f in sorted(files, key=lambda x: x.path):
        size = len(f.content.encode("utf-8"))
        lines.append(f"- `{f.path}` ({size} bytes)")
    lines.append("")
    entry = "\n".join(lines) + "\n"

    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
    if not existing.startswith("# Changelog"):
        existing = "# Changelog\n\n" + existing

    new = "# Changelog\n\n" + entry + existing[len("# Changelog\n\n"):]
    path.write_text(new, encoding="utf-8")
    return path
