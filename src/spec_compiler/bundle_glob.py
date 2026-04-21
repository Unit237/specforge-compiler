"""
`**`-aware glob matcher shared by the bundle walker and the router.

We roll our own because `fnmatch` doesn't understand `**`, and pulling in
`pathspec` for two dozen lines of code would add deadweight to every install.

Rules (same semantics as `.gitignore` / ESLint):

  - `*`  matches anything inside a single path segment
  - `?`  matches a single character inside a segment
  - `**` matches zero or more full path segments
  - literal `/` separates segments
"""

from __future__ import annotations

import fnmatch


def glob_match(path: str, pattern: str) -> bool:
    return _match_parts(path.split("/"), pattern.split("/"))


def _match_parts(rel: list[str], pat: list[str]) -> bool:
    if not pat:
        return not rel
    head, *rest = pat
    if head == "**":
        if not rest:
            return True
        for i in range(len(rel) + 1):
            if _match_parts(rel[i:], rest):
                return True
        return False
    if not rel:
        return False
    if not fnmatch.fnmatchcase(rel[0], head):
        return False
    return _match_parts(rel[1:], rest)


def match_any(path: str, patterns) -> bool:
    return any(glob_match(path, p) for p in patterns)
