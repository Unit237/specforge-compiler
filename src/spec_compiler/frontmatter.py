"""
YAML frontmatter parser.

We support the same fenced shape Jekyll / Obsidian / Eleventy use:

    ---
    spec:
      model: gpt-5
      temperature: 0.1
    any_other_key: ignored
    ---
    # Real content starts here

Only the `spec:` key is meaningful to the compiler. Every other top-level
key is returned verbatim under `extra` so downstream tools can use it without
Spec stepping on them.

Bundles without frontmatter pass through unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml


_FRONTMATTER = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*(?:\n|\Z)", re.DOTALL)


class FrontmatterError(ValueError):
    def __init__(self, message: str, *, path: str = ""):
        super().__init__(f"{path}: {message}" if path else message)
        self.path = path


@dataclass
class Parsed:
    body: str
    spec: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def has_frontmatter(self) -> bool:
        return bool(self.spec) or bool(self.extra)


# Keys the compiler understands under the `spec:` frontmatter block.
# Anything else under `spec:` raises — typos should be loud.
_ALLOWED_SPEC_KEYS = {"engine", "model", "temperature", "max_output_tokens"}


def parse(text: str, *, origin: str = "") -> Parsed:
    """
    Split `text` into (body, frontmatter). `origin` is used only for error
    messages; pass the file's relative path.
    """
    match = _FRONTMATTER.match(text)
    if not match:
        return Parsed(body=text)

    raw = match.group("body")
    body = text[match.end():]

    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as e:
        raise FrontmatterError(f"invalid YAML frontmatter: {e}", path=origin) from e

    if not isinstance(data, dict):
        raise FrontmatterError(
            "frontmatter must be a YAML mapping at the top level", path=origin
        )

    sf_raw = data.pop("spec", None)
    if sf_raw is None:
        sf: dict[str, Any] = {}
    else:
        if not isinstance(sf_raw, dict):
            raise FrontmatterError(
                "`spec:` in frontmatter must be a mapping", path=origin
            )
        unknown = set(sf_raw.keys()) - _ALLOWED_SPEC_KEYS
        if unknown:
            raise FrontmatterError(
                f"unknown key(s) under `spec:`: {sorted(unknown)}. "
                f"Allowed: {sorted(_ALLOWED_SPEC_KEYS)}",
                path=origin,
            )
        sf = sf_raw

    return Parsed(body=body, spec=sf, extra=data)
