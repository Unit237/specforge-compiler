"""
Walk a bundle and assemble the document the LLM will read.

We resolve `spec.entry` first (always), then every path matched by
`spec.include` minus `spec.exclude`, in include-glob order (top → bottom, per
PLAN §3). Paths are deduped; the entry is never emitted twice.

Output is a single markdown document where each source file is fenced with a
header so the model can tell them apart:

    # File: docs/product.md

    <content of docs/product.md>

    ---

    # File: docs/auth.md

    <content of docs/auth.md>
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .constants import (
    MANIFEST_FILENAME,
    PROMPTS_CURATED_DIRNAME,
    PROMPTS_PENDING_DIRNAME,
    is_bundle_md,
    is_session_file,
    is_spec_file,
)
from . import frontmatter as _fm
from .schema import Manifest, parse_manifest


class BundleError(ValueError):
    pass


@dataclass
class SourceFile:
    rel: str
    abs_path: Path
    content: str                                  # body only (frontmatter stripped)
    frontmatter: dict[str, Any] = field(default_factory=dict)
    raw: str = ""                                 # original bytes, including frontmatter


@dataclass
class Bundle:
    root: Path
    manifest: Manifest
    sources: list[SourceFile]
    prompts: list[SourceFile]


def load_bundle(root: Path) -> Bundle:
    root = root.resolve()
    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise BundleError(f"No {MANIFEST_FILENAME} at {root}.")

    with manifest_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    manifest = parse_manifest(data)

    sources = _collect_sources(root, manifest)
    prompts = _collect_prompts(root, manifest)

    # Bundle invariant from PLAN §2: at least one .md + exactly one manifest.
    if not sources:
        raise BundleError(
            "Bundle has no .md files matching `spec.include`. Add at least one "
            "spec document or broaden the include globs."
        )

    return Bundle(root=root, manifest=manifest, sources=sources, prompts=prompts)


def _rel(root: Path, path: Path) -> str:
    return PurePosixPath(path.resolve().relative_to(root)).as_posix()


def _read_source(root: Path, abs_path: Path) -> SourceFile:
    rel = _rel(root, abs_path)
    try:
        raw = abs_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise BundleError(f"{rel}: not valid UTF-8 ({e})") from e

    # `.prompts` files are TOML, not Markdown. Feeding them through the
    # YAML-frontmatter parser would either no-op (they don't start with
    # `---`) or blow up on the first hand-authored file that happens to.
    # Keep them on the "raw" rail and let routing + prompt assembly deal
    # with them specifically. This mirrors the CLI/server classifier:
    # `.prompts` is a kind unto itself, not just another `.md`.
    if is_session_file(rel):
        return SourceFile(rel=rel, abs_path=abs_path, content=raw, raw=raw)

    parsed = _fm.parse(raw, origin=rel)
    return SourceFile(
        rel=rel,
        abs_path=abs_path,
        content=parsed.body,
        frontmatter=parsed.spec,
        raw=raw,
    )


def _collect_sources(root: Path, manifest: Manifest) -> list[SourceFile]:
    """Walk the bundle and collect every `.md` file the resolver accepts.

    The membership question is delegated to
    ``constants.is_bundle_md`` — the same resolver the CLI runs at
    ``spec status`` / ``spec add`` time and the Cloud surfaces in the
    file tree. That's what makes "what's in the bundle on disk", "what
    `spec compile` reads", and "what shows up in the Cloud bundle
    view" all answer the same question (PLAN.md §2.1).
    """
    # The compiler's `Manifest` dataclass exposes the `spec` block as
    # an object; the resolver wants a mapping. Rebuild a small dict so
    # we don't leak the dataclass into the resolver's API contract
    # (the CLI side uses a raw mapping).
    spec_mapping: dict[str, Any] = {
        "include": list(manifest.spec.include or []),
        "exclude": list(manifest.spec.exclude or []),
    }

    ordered: list[Path] = []
    seen: set[str] = set()

    # Entry always first — even if it'd otherwise be excluded by the
    # resolver, an explicit `spec.entry` is the user's most direct
    # statement of intent. We still skip the manifest itself and
    # require the file to exist.
    entry_abs = (root / manifest.spec.entry).resolve()
    if entry_abs.is_file():
        rel = _rel(root, entry_abs)
        if PurePosixPath(rel).name != MANIFEST_FILENAME and is_spec_file(rel):
            ordered.append(entry_abs)
            seen.add(rel)

    for abs_path in sorted(root.rglob("*")):
        if not abs_path.is_file():
            continue
        rel = _rel(root, abs_path)
        if rel in seen:
            continue
        if not is_spec_file(rel) or PurePosixPath(rel).name == MANIFEST_FILENAME:
            continue
        if any(part.startswith(".") for part in PurePosixPath(rel).parts[:-1]):
            continue
        # `.prompts` files have their own assembly path and are walked
        # separately by `_collect_prompts`; skip them here so the spec
        # walk stays markdown-only.
        if is_session_file(rel):
            continue
        # Read frontmatter once so the resolver can honour `spec: true /
        # false` overrides. Errors fall through to "no frontmatter".
        try:
            text_for_fm = abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text_for_fm = ""
        try:
            parsed = _fm.parse(text_for_fm, origin=rel)
            fm_dict: dict[str, Any] = {}
            if parsed.spec:
                fm_dict["spec"] = parsed.spec
        except Exception:
            fm_dict = {}
        if not is_bundle_md(rel, manifest_spec=spec_mapping, frontmatter=fm_dict):
            continue
        ordered.append(abs_path)
        seen.add(rel)

    return [_read_source(root, p) for p in ordered]


def _collect_prompts(root: Path, manifest: Manifest) -> list[SourceFile]:
    """Walk the prompts directory and return every compilable `.prompts` file.

    Deliberately excludes anything under `<prompts>/curated/_pending/` — the
    pending subdirectory is the review-staging area, and by contract its
    contents have not been approved by a human reviewer yet. Letting those
    files into compilation would make it trivial to ship an un-reviewed
    prompt into production, which is exactly what the review workflow
    exists to prevent.

    Captured and curated tiers are both included (the compiler treats them
    uniformly at the grouping layer; the CLI's compile-prompt assembler is
    where tier labelling matters). Legacy files at the prompts root are
    grandfathered.
    """
    prompts_dir = (root / manifest.prompts.directory).resolve()
    if not prompts_dir.is_dir():
        return []
    pending_dir = prompts_dir / PROMPTS_CURATED_DIRNAME / PROMPTS_PENDING_DIRNAME
    out: list[SourceFile] = []
    for p in sorted(prompts_dir.rglob("*")):
        if not p.is_file() or not is_spec_file(p.name):
            continue
        # Exclude anything inside the pending-review staging area. Compare
        # on resolved paths so symlinks can't sneak around the guard.
        try:
            p.resolve().relative_to(pending_dir.resolve())
        except ValueError:
            pass
        else:
            continue
        out.append(_read_source(root, p))
    return out


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def assemble_spec_document(sources: list[SourceFile]) -> str:
    """The markdown document we hand to the model for one LLM call."""
    chunks: list[str] = []
    for src in sources:
        chunks.append(f"# File: {src.rel}\n\n{src.content.rstrip()}\n")
    return "\n---\n\n".join(chunks) + "\n"


def assemble_prompts(prompts: list[SourceFile]) -> str:
    if not prompts:
        return ""
    chunks: list[str] = []
    for p in prompts:
        chunks.append(f"## Prompt: {p.rel}\n\n{p.content.rstrip()}\n")
    return "\n".join(chunks)
