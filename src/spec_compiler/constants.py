"""
Shared extension allow-list.

Keep in agreement with `spec-cli`'s `spec_cli/constants.py` and with
Spec Cloud's validator. The values here are authoritative for the
compiler's own file I/O.
"""

from __future__ import annotations

from pathlib import PurePosixPath

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
