"""
Parse the compiler's LLM response into files-on-disk.

Output contract (v0.1):

The model must emit one or more `<file path="...">...</file>` blocks.
Anything outside of file blocks is ignored (treated as commentary). This
format is chosen because:

  - it's robust to code that contains triple-backtick fences
  - it's easy to stream-parse
  - it's trivially diffable against `<file>`-producing tools elsewhere

We intentionally do NOT allow filenames escaping the output target. Any path
that, after join + resolve, lands outside `output.target` is rejected.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


_FILE_BLOCK = re.compile(
    r'<file\s+path=(?P<quote>["\'])(?P<path>.+?)(?P=quote)\s*>'
    r"(?P<body>.*?)"
    r"</file>",
    re.DOTALL | re.IGNORECASE,
)


class OutputError(ValueError):
    pass


@dataclass
class GeneratedFile:
    path: str           # relative, posix
    content: str


def parse_file_blocks(text: str) -> list[GeneratedFile]:
    files: list[GeneratedFile] = []
    for m in _FILE_BLOCK.finditer(text or ""):
        path = m.group("path").strip()
        body = m.group("body")
        if body.startswith("\n"):
            body = body[1:]
        if body.endswith("\n"):
            pass
        else:
            body = body + "\n"
        files.append(GeneratedFile(path=path, content=body))
    return files


def write_outputs(
    target_root: Path, files: list[GeneratedFile], *, dry_run: bool = False
) -> list[Path]:
    """Write files beneath `target_root`. Returns the list of paths written."""
    target_root = target_root.resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for f in files:
        rel = f.path.lstrip("/")
        dest = (target_root / rel).resolve()

        try:
            dest.relative_to(target_root)
        except ValueError as e:
            raise OutputError(
                f"Refusing to write `{f.path}` — escapes output target "
                f"{target_root}."
            ) from e

        if dry_run:
            written.append(dest)
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f.content, encoding="utf-8")
        written.append(dest)

    return written


def summarize(files: list[GeneratedFile]) -> str:
    if not files:
        return "0 files"
    total_bytes = sum(len(f.content.encode("utf-8")) for f in files)
    return f"{len(files)} file(s), {total_bytes} bytes"


def humanize_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB"):
        if nbytes < 1024 or unit == "MB":
            return f"{nbytes:.0f} {unit}" if unit == "B" else f"{nbytes/1024:.1f} {unit}"
        nbytes //= 1024
    return f"{nbytes} B"


def relpath(root: Path, p: Path) -> str:
    try:
        return os.path.relpath(p, root)
    except ValueError:
        return str(p)
