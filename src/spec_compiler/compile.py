"""
The compilation orchestrator.

Flow:
  1. Load the bundle (schema-validate the manifest, walk the spec files).
     Each file's YAML frontmatter is parsed and stripped from the body.
  2. Resolve the compiler config for each spec file:
         frontmatter  >  routes  >  compiler defaults
  3. Group files by resolved config. Files that share a config are compiled
     in a single LLM call (assembled into one document). Different configs
     produce separate calls.
  4. For each group:
       - assemble the system prompt from `prompts/`
       - invoke the engine
       - parse `<file>` blocks out of the response
  5. Merge all generated files across groups. Conflicting paths (two groups
     emitting the same output file) is a hard error.
  6. Write them to `output.target` with a path-escape guard.
  7. Optionally emit a `CHANGELOG.md` delta.
  8. Optionally POST a run record to Spec Cloud (hashes only — the raw
     output never leaves the user's laptop).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .bundle import Bundle, SourceFile, assemble_prompts, assemble_spec_document, load_bundle
from .changelog import write_changelog
from .engines import Call, engine_for
from .output import GeneratedFile, OutputError, parse_file_blocks, write_outputs
from .prompts_routing import (
    SessionResolution,
    gather_sessions,
    sessions_for_config,
)
from .routing import ResolvedConfig, Resolution, group_by_config, resolve


DEFAULT_SYSTEM_PROMPT = (
    "You are the Spec compiler. You are given a single document that "
    "concatenates every spec file in a bundle (each preceded by a `# File: <path>` "
    "header) and a set of prompt templates. Produce one or more files that "
    "implement the spec.\n\n"
    "OUTPUT CONTRACT — non-negotiable:\n"
    "  - Emit each file as a `<file path=\"relative/path\">...</file>` block.\n"
    "  - Paths are relative to the output root and must not escape it.\n"
    "  - Anything outside a `<file>` block is ignored as commentary.\n"
    "  - Do not wrap file contents in markdown fences — emit the raw bytes.\n"
)


@dataclass
class CompileOptions:
    dry_run: bool = False
    out_override: Path | None = None
    model_override: str | None = None
    engine_override: str | None = None
    record_url: str | None = None
    record_token: str | None = None


@dataclass
class GroupResult:
    config: ResolvedConfig
    members: list[Resolution]
    files: list[GeneratedFile]
    duration_ms: int = 0
    sessions: list[SessionResolution] = field(default_factory=list)


@dataclass
class CompileResult:
    bundle: Bundle
    resolutions: list[Resolution]
    groups: list[GroupResult]
    config_hash: str
    output_hash: str
    files: list[GeneratedFile]
    written: list[Path]
    target: Path
    duration_ms: int
    dry_run: bool


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _sha256_files(files: list[GeneratedFile]) -> str:
    h = hashlib.sha256()
    for f in sorted(files, key=lambda x: x.path):
        h.update(f.path.encode("utf-8"))
        h.update(b"\x00")
        h.update(f.content.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _config_hash(bundle: Bundle, resolutions: list[Resolution]) -> str:
    """
    Hash of everything that went into compilation decisions:

      - schema version
      - every source file's sha (body only, frontmatter-stripped)
      - every prompt file's sha (body only)
      - the resolved config for each source (so routing changes show up in
        drift even if no file content changed)

    Cloud stores this as part of the run record and uses it to detect drift
    (§5: "drift chip when the latest bundle hasn't been compiled").
    """
    payload = {
        "schema": bundle.manifest.schema,
        "sources": [
            {"path": s.rel, "sha": _sha256_text(s.content)} for s in bundle.sources
        ],
        "prompts": [
            {"path": p.rel, "sha": _sha256_text(p.content)} for p in bundle.prompts
        ],
        "resolved": [
            {
                "path": r.path,
                "engine": r.config.engine,
                "model": r.config.model,
                "temperature": r.config.temperature,
                "max_output_tokens": r.config.max_output_tokens,
            }
            for r in resolutions
        ],
    }
    return _sha256_text(json.dumps(payload, sort_keys=True))


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


class ConflictError(OutputError):
    pass


def _merge_files(groups: list[GroupResult]) -> list[GeneratedFile]:
    """
    Flatten every group's output into one list. If two groups emitted the
    same output path with different content, error out with a precise
    message — silent last-write-wins would be a debugging nightmare.
    """
    seen: dict[str, tuple[str, GeneratedFile]] = {}  # path → (group_label, file)
    for g in groups:
        label = f"{g.config.engine}/{g.config.model}"
        for f in g.files:
            prev = seen.get(f.path)
            if prev is None:
                seen[f.path] = (label, f)
                continue
            other_label, other = prev
            if other.content == f.content:
                # Identical output from two groups — benign, keep one.
                continue
            raise ConflictError(
                f"Two compilation groups emitted `{f.path}` with different content:\n"
                f"  - {other_label}\n"
                f"  - {label}\n"
                "Either narrow the routes so only one group generates it, "
                "or route the governing spec file to a single model."
            )
    return [pair[1] for pair in seen.values()]


# ---------------------------------------------------------------------------
# Prompt selection per group
# ---------------------------------------------------------------------------


def _prompts_for_group(
    all_prompts: list[SourceFile], group_sessions: list[SessionResolution]
) -> list[SourceFile]:
    """
    Pick the subset of ``.prompts`` files whose rendered body includes at
    least one session routed to this group. A single ``.prompts`` file may
    contain sessions that land on different models — in v0.1 we include
    the whole file whenever any of its sessions are relevant, because the
    commit-level context (branch, author, siblings) is part of the signal.
    Splitting one file into per-model partial renders is a v0.2 concern.
    """
    if not all_prompts:
        return []
    relevant_paths = {s.ref.prompts_path for s in group_sessions}
    return [p for p in all_prompts if p.rel in relevant_paths]


# ---------------------------------------------------------------------------
# Overrides from CLI flags
# ---------------------------------------------------------------------------


def _apply_cli_overrides(resolutions: list[Resolution], opts: CompileOptions) -> list[Resolution]:
    """
    `--model` and `--engine` override every resolution uniformly. They're
    the "I'm debugging, ignore routing" escape hatch.
    """
    if not opts.model_override and not opts.engine_override:
        return resolutions

    new: list[Resolution] = []
    for r in resolutions:
        cfg = ResolvedConfig(
            engine=opts.engine_override or r.config.engine,
            model=opts.model_override or r.config.model,
            temperature=r.config.temperature,
            max_output_tokens=r.config.max_output_tokens,
        )
        from .routing import TrailStep
        trail = list(r.trail)
        over: dict = {}
        if opts.engine_override:
            over["engine"] = opts.engine_override
        if opts.model_override:
            over["model"] = opts.model_override
        trail.append(TrailStep(tier="cli", source="cli-flag", overrides=over))
        new.append(Resolution(path=r.path, config=cfg, trail=trail))
    return new


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_bundle(root: Path, opts: CompileOptions | None = None) -> CompileResult:
    opts = opts or CompileOptions()
    t_total = time.monotonic()

    bundle = load_bundle(root)

    # Resolve a config for every spec file. This is path+frontmatter-based
    # (tier 2 + 3 in routing.resolve). Prompts are routed separately below
    # because they carry per-session model pins that override the file path.
    resolutions = [
        resolve(s.rel, bundle.manifest, frontmatter=s.frontmatter)
        for s in bundle.sources
    ]
    resolutions = _apply_cli_overrides(resolutions, opts)

    # Per-session prompt routing. Each `[[sessions]]` block is resolved
    # independently (session.model > route-on-prompts-path > defaults) and
    # attached to the group whose resolved config matches. Sessions without
    # a pinned model are portable and ride with every group. See
    # prompts_routing.py for the contract.
    all_sessions = gather_sessions(bundle.prompts, bundle.manifest)
    if opts.model_override or opts.engine_override:
        # CLI override pins every call to the same config — all sessions
        # ride on every call, since there is only one.
        all_sessions = [
            SessionResolution(
                ref=s.ref,
                config=ResolvedConfig(
                    engine=opts.engine_override or s.config.engine,
                    model=opts.model_override or s.config.model,
                    temperature=s.config.temperature,
                    max_output_tokens=s.config.max_output_tokens,
                ),
                source="cli-override",
            )
            for s in all_sessions
        ]

    cfg_hash = _config_hash(bundle, resolutions)

    # Group files by their resolved config.
    source_by_path = {s.rel: s for s in bundle.sources}
    grouped = group_by_config(resolutions)
    groups: list[GroupResult] = []

    if opts.dry_run:
        for cfg, members in grouped:
            groups.append(
                GroupResult(
                    config=cfg,
                    members=members,
                    files=[],
                    sessions=sessions_for_config(all_sessions, cfg),
                )
            )
    else:
        for cfg, members in grouped:
            t0 = time.monotonic()
            engine = engine_for(cfg.engine)
            chunk_sources = [source_by_path[m.path] for m in members]

            # Sessions that belong to this group's model (plus portable
            # sessions). Build a SourceFile stand-in for each so we can
            # reuse assemble_prompts' formatting.
            group_sessions = sessions_for_config(all_sessions, cfg)
            group_prompts = _prompts_for_group(bundle.prompts, group_sessions)
            prompts_body = assemble_prompts(group_prompts)

            system = DEFAULT_SYSTEM_PROMPT
            if prompts_body:
                system = system + "\n\n---\n\n" + prompts_body

            user = assemble_spec_document(chunk_sources)
            call = Call(
                model=cfg.model,
                system=system,
                user=user,
                temperature=cfg.temperature,
                max_output_tokens=cfg.max_output_tokens,
            )
            response_text = engine.run(call)
            files = parse_file_blocks(response_text)
            groups.append(
                GroupResult(
                    config=cfg,
                    members=members,
                    files=files,
                    sessions=group_sessions,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
            )

    merged = [] if opts.dry_run else _merge_files(groups)

    target = (
        opts.out_override.resolve()
        if opts.out_override
        else (root / bundle.manifest.output.target).resolve()
    )
    written = write_outputs(target, merged, dry_run=opts.dry_run)

    if not opts.dry_run and bundle.manifest.output.changelog and merged:
        write_changelog(
            target,
            merged,
            bundle=bundle,
            commit_style=bundle.manifest.output.commit_style,
        )

    out_hash = _sha256_files(merged) if merged else _sha256_text("")
    duration_ms = int((time.monotonic() - t_total) * 1000)

    if opts.record_url and not opts.dry_run:
        _post_run_record(
            url=opts.record_url,
            token=opts.record_token,
            bundle=bundle,
            config_hash=cfg_hash,
            output_hash=out_hash,
            n_files=len(merged),
            duration_ms=duration_ms,
            groups=groups,
        )

    return CompileResult(
        bundle=bundle,
        resolutions=resolutions,
        groups=groups,
        config_hash=cfg_hash,
        output_hash=out_hash,
        files=merged,
        written=written,
        target=target,
        duration_ms=duration_ms,
        dry_run=opts.dry_run,
    )


def _post_run_record(
    *,
    url: str,
    token: str | None,
    bundle: Bundle,
    config_hash: str,
    output_hash: str,
    n_files: int,
    duration_ms: int,
    groups: list[GroupResult],
) -> None:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {
        "project_slug": bundle.manifest.cloud.project,
        "config_hash": config_hash,
        "output_hash": output_hash,
        "n_files": n_files,
        "duration_ms": duration_ms,
        "groups": [
            {
                "engine": g.config.engine,
                "model": g.config.model,
                "temperature": g.config.temperature,
                "max_output_tokens": g.config.max_output_tokens,
                "members": [m.path for m in g.members],
                "n_output_files": len(g.files),
                "duration_ms": g.duration_ms,
                # Per-session routing trail so the Cloud UI can explain
                # *why* a session ended up on this model.
                "sessions": [
                    {
                        "file": s.ref.prompts_path,
                        "id": s.ref.session_id,
                        "model_pin": s.ref.model,
                        "routed_via": s.source,
                    }
                    for s in g.sessions
                ],
            }
            for g in groups
        ],
    }
    try:
        requests.post(url.rstrip("/") + "/api/runs", json=payload, headers=headers, timeout=30)
    except requests.RequestException:
        # Recording is best-effort; compilation still succeeded locally.
        pass
