"""
Three-tier model resolution:

    frontmatter  >  routes  >  compiler defaults

First match wins inside the route table (top-to-bottom in `spec.yaml`).
Each tier is a partial override — keys not set at a tier fall through to the
next. The result is a full `ResolvedConfig` (no Nones) plus a `trail` that
tells the UI exactly why a file ended up on a given model.

No scoring, no specificity math. If two routes match, the first one wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .bundle_glob import glob_match
from .schema import CompilerSection, Manifest, Route


@dataclass(frozen=True)
class ResolvedConfig:
    """A fully-resolved compiler config — no Nones, no fall-through left."""

    engine: str
    model: str
    temperature: float
    max_output_tokens: int

    def key(self) -> tuple:
        """Hashable grouping key — files that share this are one LLM call."""
        return (self.engine, self.model, self.temperature, self.max_output_tokens)


@dataclass
class TrailStep:
    tier: str      # "default" | "route" | "frontmatter"
    source: str    # "compiler" | "route:<glob>" | "frontmatter"
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass
class Resolution:
    path: str
    config: ResolvedConfig
    trail: list[TrailStep]

    @property
    def summary(self) -> str:
        """Single-line human description for the CLI / Cloud UI pill."""
        parts = [f"compiles with {self.config.engine}/{self.config.model}"]
        last = self.trail[-1]
        if last.tier != "default":
            parts.append(f"(from {last.source})")
        return " ".join(parts)


def _apply(
    base: dict[str, Any], overrides: dict[str, Any]
) -> dict[str, Any]:
    out = dict(base)
    for k, v in overrides.items():
        if v is not None:
            out[k] = v
    return out


def resolve(
    path: str,
    manifest: Manifest,
    *,
    frontmatter: dict[str, Any] | None = None,
) -> Resolution:
    """
    Resolve the compiler config for a single file at `path` (posix-relative
    to the bundle root).
    """
    compiler: CompilerSection = manifest.compiler
    base = {
        "engine": compiler.engine,
        "model": compiler.model,
        "temperature": compiler.temperature,
        "max_output_tokens": compiler.max_output_tokens,
    }

    trail: list[TrailStep] = [
        TrailStep(tier="default", source="compiler", overrides=dict(base))
    ]

    # --- tier 2: route table (first match wins) --------------------------
    matched: Route | None = None
    for route in compiler.routes:
        if glob_match(path, route.match):
            matched = route
            break

    if matched is not None:
        over = matched.overrides
        base = _apply(base, over)
        trail.append(
            TrailStep(tier="route", source=f"route:{matched.match}", overrides=over)
        )

    # --- tier 1: frontmatter (wins over everything) ----------------------
    if frontmatter:
        base = _apply(base, frontmatter)
        trail.append(
            TrailStep(tier="frontmatter", source="frontmatter", overrides=dict(frontmatter))
        )

    return Resolution(
        path=path,
        config=ResolvedConfig(
            engine=str(base["engine"]),
            model=str(base["model"]),
            temperature=float(base["temperature"]),
            max_output_tokens=int(base["max_output_tokens"]),
        ),
        trail=trail,
    )


def group_by_config(resolutions: list[Resolution]) -> list[tuple[ResolvedConfig, list[Resolution]]]:
    """
    Group resolutions by config key. Stable: group order follows first
    appearance in the input list, so the CLI output mirrors manifest order.
    """
    order: list = []
    buckets: dict = {}
    for r in resolutions:
        k = r.config.key()
        if k not in buckets:
            buckets[k] = (r.config, [])
            order.append(k)
        buckets[k][1].append(r)
    return [buckets[k] for k in order]
