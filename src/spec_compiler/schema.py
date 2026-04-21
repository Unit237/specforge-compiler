"""
spec.yaml schema (v0.1) — open source.

This is the authoritative validator for the manifest. Cloud stores and diffs
the YAML but does not validate structure. The CLI defers here for `init`
scaffolding and `compile` hand-off.

We avoid pulling in pydantic / jsonschema to keep dependency weight low.
Validation is a handful of conditionals that produce precise error messages
— the user is reading plain English, we should do them the courtesy of
writing errors in it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import SCHEMA_VERSION
from .constants import PROMPTS_DIRECTORY_DEFAULT


class SchemaError(ValueError):
    def __init__(self, message: str, *, path: str = ""):
        location = f"{path}: " if path else ""
        super().__init__(f"{location}{message}")
        self.path = path


# ---------------------------------------------------------------------------
# Parsed shape
# ---------------------------------------------------------------------------


@dataclass
class SpecSection:
    entry: str
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


@dataclass
class PromptsSection:
    directory: str = PROMPTS_DIRECTORY_DEFAULT


_VALID_ENGINES = frozenset({"openai", "anthropic", "local", "custom"})


@dataclass
class Route:
    """
    One entry in the `compiler.routes` table.

    `match` is a glob pattern (same semantics as `spec.include`). Any of the
    other fields may be None — a route only overrides what it sets. `None`
    means "inherit from `compiler.*` defaults".
    """

    match: str
    engine: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None

    @property
    def overrides(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.engine is not None:
            out["engine"] = self.engine
        if self.model is not None:
            out["model"] = self.model
        if self.temperature is not None:
            out["temperature"] = self.temperature
        if self.max_output_tokens is not None:
            out["max_output_tokens"] = self.max_output_tokens
        return out


@dataclass
class CompilerSection:
    # Claude-first by default. The CLI's `spec compile` flow hands work
    # to Claude Code; `--via api` and `spec-compile` target the same
    # model family so the generated artifacts stay consistent whichever
    # path the user takes.
    engine: str = "anthropic"
    model: str = "claude-sonnet-4-5"
    temperature: float = 0.2
    max_output_tokens: int = 8000
    routes: list[Route] = field(default_factory=list)


@dataclass
class OutputSection:
    target: str = "./out"
    changelog: bool = True
    commit_style: str = "conventional"  # conventional | plain | none


@dataclass
class ApprovalsSection:
    required: int = 0


@dataclass
class CloudSection:
    project: str | None = None


@dataclass
class Manifest:
    schema: str
    name: str
    description: str
    spec: SpecSection
    prompts: PromptsSection
    compiler: CompilerSection
    output: OutputSection
    approvals: ApprovalsSection
    cloud: CloudSection
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parsing / validation
# ---------------------------------------------------------------------------


def _require_mapping(value: Any, *, path: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SchemaError("expected a mapping", path=path)
    return value


def _require_str(value: Any, *, path: str, default: str | None = None) -> str:
    if value is None:
        if default is not None:
            return default
        raise SchemaError("expected a string", path=path)
    if not isinstance(value, str):
        raise SchemaError("expected a string", path=path)
    return value


def _require_list_of_str(value: Any, *, path: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SchemaError("expected a list of strings", path=path)
    out = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise SchemaError("expected a string", path=f"{path}[{i}]")
        out.append(item)
    return out


def _parse_routes(value: Any) -> list[Route]:
    """
    Parse `compiler.routes`. Each entry must be a mapping with a `match` key
    and at least one override. Unknown keys are rejected — we want drift in
    the schema to surface loudly, not silently.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise SchemaError("expected a list of route mappings", path="compiler.routes")

    allowed_keys = {"match", "engine", "model", "temperature", "max_output_tokens"}
    routes: list[Route] = []
    for i, item in enumerate(value):
        where = f"compiler.routes[{i}]"
        if not isinstance(item, dict):
            raise SchemaError("expected a mapping", path=where)

        unknown = set(item.keys()) - allowed_keys
        if unknown:
            raise SchemaError(
                f"unknown key(s): {sorted(unknown)}. Allowed: {sorted(allowed_keys)}",
                path=where,
            )

        match = _require_str(item.get("match"), path=f"{where}.match")
        engine = item.get("engine")
        if engine is not None:
            engine = _require_str(engine, path=f"{where}.engine")
            if engine not in _VALID_ENGINES:
                raise SchemaError(
                    f"unknown engine `{engine}`. Valid: {', '.join(sorted(_VALID_ENGINES))}",
                    path=f"{where}.engine",
                )

        model = item.get("model")
        if model is not None:
            model = _require_str(model, path=f"{where}.model")

        temperature = item.get("temperature")
        if temperature is not None:
            try:
                temperature = float(temperature)
            except (TypeError, ValueError) as e:
                raise SchemaError("expected a number", path=f"{where}.temperature") from e

        max_output_tokens = item.get("max_output_tokens")
        if max_output_tokens is not None:
            try:
                max_output_tokens = int(max_output_tokens)
            except (TypeError, ValueError) as e:
                raise SchemaError("expected an integer", path=f"{where}.max_output_tokens") from e

        route = Route(
            match=match,
            engine=engine,
            model=model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        if not route.overrides:
            raise SchemaError(
                "a route must override at least one of "
                "engine / model / temperature / max_output_tokens",
                path=where,
            )

        routes.append(route)

    return routes


def parse_manifest(data: dict[str, Any]) -> Manifest:
    if not isinstance(data, dict):
        raise SchemaError("manifest must be a YAML mapping at the top level")

    schema_value = data.get("schema")
    if not schema_value:
        raise SchemaError(
            "missing required key `schema`. Expected `schema: \"spec/v0.1\"`. "
            "See https://spec.lightreach.io/docs/manifest"
        )
    if schema_value != SCHEMA_VERSION:
        raise SchemaError(
            f"unsupported schema `{schema_value}`. This compiler understands "
            f"`{SCHEMA_VERSION}`. Upgrade `spec-compiler` or pin the manifest.",
            path="schema",
        )

    name = _require_str(data.get("name"), path="name")
    description = _require_str(data.get("description"), path="description", default="")

    spec_raw = _require_mapping(data.get("spec"), path="spec")
    spec = SpecSection(
        entry=_require_str(spec_raw.get("entry"), path="spec.entry"),
        include=_require_list_of_str(spec_raw.get("include"), path="spec.include"),
        exclude=_require_list_of_str(spec_raw.get("exclude"), path="spec.exclude"),
    )

    prompts_raw = _require_mapping(data.get("prompts"), path="prompts")
    prompts = PromptsSection(
        directory=_require_str(
            prompts_raw.get("directory"),
            path="prompts.directory",
            default=PROMPTS_DIRECTORY_DEFAULT,
        ),
    )

    compiler_raw = _require_mapping(data.get("compiler"), path="compiler")
    engine = _require_str(
        compiler_raw.get("engine"), path="compiler.engine", default="anthropic"
    )
    if engine not in _VALID_ENGINES:
        raise SchemaError(
            f"unknown engine `{engine}`. Valid: {', '.join(sorted(_VALID_ENGINES))}",
            path="compiler.engine",
        )
    routes = _parse_routes(compiler_raw.get("routes"))
    compiler = CompilerSection(
        engine=engine,
        model=_require_str(
            compiler_raw.get("model"),
            path="compiler.model",
            default="claude-sonnet-4-5",
        ),
        temperature=float(compiler_raw.get("temperature", 0.2)),
        max_output_tokens=int(compiler_raw.get("max_output_tokens", 8000)),
        routes=routes,
    )

    output_raw = _require_mapping(data.get("output"), path="output")
    output = OutputSection(
        target=_require_str(output_raw.get("target"), path="output.target", default="./out"),
        changelog=bool(output_raw.get("changelog", True)),
        commit_style=_require_str(
            output_raw.get("commit_style"),
            path="output.commit_style",
            default="conventional",
        ),
    )
    if output.commit_style not in {"conventional", "plain", "none"}:
        raise SchemaError(
            f"unknown commit_style `{output.commit_style}`",
            path="output.commit_style",
        )

    approvals_raw = _require_mapping(data.get("approvals"), path="approvals")
    approvals = ApprovalsSection(required=int(approvals_raw.get("required", 0)))

    cloud_raw = _require_mapping(data.get("cloud"), path="cloud")
    cloud = CloudSection(project=cloud_raw.get("project"))

    return Manifest(
        schema=schema_value,
        name=name,
        description=description,
        spec=spec,
        prompts=prompts,
        compiler=compiler,
        output=output,
        approvals=approvals,
        cloud=cloud,
        raw=data,
    )
