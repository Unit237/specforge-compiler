"""
Shared extension allow-list and bundle-membership resolver.

Keep in agreement with `spec-cli`'s `spec_cli/constants.py` and with
Spec Cloud's validator. The values here are authoritative for the
compiler's own file I/O.

The bundle-membership resolver (``is_bundle_md``) is mirrored verbatim
from ``spec_cli.constants`` — see PLAN.md §2.1 for the design and the
truth-table tests in ``tests/test_is_bundle_md.py`` for the contract.
We intentionally do NOT depend on ``spec-cli`` (the compiler must
install standalone), so any change here needs the symmetric change
in the CLI repo.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Mapping

from .bundle_glob import match_any as _match_any

SPEC_EXTENSIONS: frozenset[str] = frozenset({".md", ".markdown", ".prompts"})
MANIFEST_FILENAME: str = "spec.yaml"
PROMPTS_DIRECTORY_DEFAULT: str = "prompts"

# Two-tier layout under the prompts directory. Must stay in sync with the
# CLI's `spec_cli.constants` — both packages agree on where captured vs.
# curated prompts live, and which subdirectory is the pending-review staging
# area that the compiler refuses to read.
PROMPTS_CAPTURED_DIRNAME: str = "captured"
PROMPTS_CURATED_DIRNAME: str = "curated"
PROMPTS_PENDING_DIRNAME: str = "_pending"

# File extensions the compiler folds into the assembled user document. We
# intentionally EXCLUDE `.prompts` — those are conversation history, handled
# separately by the prompt-context assembler (see
# ``bundle.py::assemble_prompts``). The compile pipeline keeps intent
# (``.md``) and history (``.prompts``) on distinct rails so edits to one
# don't silently change the other's grouping.
#
# Naming is plural: one ``.prompts`` file per commit contains many
# ``[[sessions]]`` (see spec-cli/docs/prompt-format.md). The singular
# ``.prompt`` extension is not a thing in v0.1 — this package used to use
# it, which meant the compiler silently ignored every ``.prompts`` file
# the CLI produced. Do not reintroduce the singular.
SPEC_DOC_EXTENSIONS: frozenset[str] = frozenset({".md", ".markdown"})
SESSION_EXTENSION: str = ".prompts"


# ---------------------------------------------------------------------------
# Bundle-membership resolver — mirror of `spec_cli.constants`.
# Keep these three constants byte-identical across the two repos.
# ---------------------------------------------------------------------------

AGENT_INSTRUCTION_FILENAMES: frozenset[str] = frozenset(
    {
        "agents.md",
        "claude.md",
        "gemini.md",
        "llms.txt",
        "llms-full.txt",
    }
)
AGENT_INSTRUCTION_PATTERNS: tuple[str, ...] = (
    ".github/copilot-instructions.md",
)
HUMAN_DOC_FILENAMES: frozenset[str] = frozenset(
    {
        "readme.md",
        "readme.markdown",
        "changelog.md",
        "contributing.md",
        "code_of_conduct.md",
        "security.md",
        "license",
        "license.md",
        "license.txt",
        "notice",
        "notice.md",
        "history.md",
        "roadmap.md",
    }
)
DEFAULT_SPEC_INCLUDE: tuple[str, ...] = ("docs/**/*.md",)


def is_spec_file(path: str | PurePosixPath) -> bool:
    p = PurePosixPath(str(path))
    if p.name == MANIFEST_FILENAME:
        return True
    return p.suffix.lower() in SPEC_EXTENSIONS


def is_spec_doc(path: str | PurePosixPath) -> bool:
    """A traditional Markdown spec doc (intent). Excludes `.prompt` sessions."""
    return PurePosixPath(str(path)).suffix.lower() in SPEC_DOC_EXTENSIONS


def is_session_file(path: str | PurePosixPath) -> bool:
    """A captured or hand-authored `.prompt` session file."""
    return PurePosixPath(str(path)).suffix.lower() == SESSION_EXTENSION


def _is_agent_instruction(rel_lower: str) -> bool:
    name = PurePosixPath(rel_lower).name
    if name in AGENT_INSTRUCTION_FILENAMES:
        return True
    return _match_any(rel_lower, AGENT_INSTRUCTION_PATTERNS)


def _is_human_doc(rel_lower: str) -> bool:
    name = PurePosixPath(rel_lower).name
    return name in HUMAN_DOC_FILENAMES


def is_bundle_md(
    rel: str | PurePosixPath,
    *,
    manifest_spec: Mapping[str, Any] | None = None,
    frontmatter: Mapping[str, Any] | None = None,
) -> bool:
    """Bundle-membership resolver for `.md` files.

    See ``spec_cli.constants.is_bundle_md`` for the canonical
    docstring and the truth table. The two implementations must agree
    for every input — that's what makes the CLI's "what gets staged"
    match the compiler's "what gets compiled".

    `manifest_spec` is the parsed `spec` *section* of the manifest
    (i.e. ``manifest.spec``), not the whole manifest — the compiler's
    schema dataclass already gives us the section directly so this
    saves a layer of lookups.
    """
    rel_str = str(rel)
    rel_lower = rel_str.lower()
    if not (rel_lower.endswith(".md") or rel_lower.endswith(".markdown")):
        return False

    if frontmatter is not None and isinstance(frontmatter, Mapping):
        spec_fm = frontmatter.get("spec")
        if isinstance(spec_fm, bool):
            return spec_fm
        if isinstance(spec_fm, Mapping):
            inc = spec_fm.get("include")
            if isinstance(inc, bool):
                return inc

    explicit_include: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    has_explicit_include = False
    if manifest_spec is not None:
        raw_inc = manifest_spec.get("include") if isinstance(manifest_spec, Mapping) else None
        if isinstance(raw_inc, list) and raw_inc:
            explicit_include = tuple(p for p in raw_inc if isinstance(p, str))
            has_explicit_include = True
        raw_exc = manifest_spec.get("exclude") if isinstance(manifest_spec, Mapping) else None
        if isinstance(raw_exc, list):
            excludes = tuple(p for p in raw_exc if isinstance(p, str))

    if excludes and _match_any(rel_str, excludes):
        return False
    if has_explicit_include and _match_any(rel_str, explicit_include):
        return True
    if _is_agent_instruction(rel_lower):
        return True
    if _is_human_doc(rel_lower):
        return False
    if not has_explicit_include and _match_any(rel_str, DEFAULT_SPEC_INCLUDE):
        return True
    return False
