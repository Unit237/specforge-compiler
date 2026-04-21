"""`spec-compile` — CLI wrapper around `compile.compile_bundle`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.theme import Theme

from . import __version__
from .bundle import BundleError
from .compile import CompileOptions, compile_bundle
from .engines import EngineError
from .frontmatter import FrontmatterError
from .output import OutputError
from .schema import SchemaError


_theme = Theme(
    {
        "sf.mint": "bold #3ddab4",
        "sf.reject": "bold #ff5a6a",
        "sf.muted": "dim #9aa3b2",
        "sf.point": "bold #7de3ff",
        "sf.label": "bold #c7c9d1",
    }
)
console = Console(theme=_theme, highlight=False)
err = Console(theme=_theme, stderr=True, highlight=False)


@click.command(
    context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 100}
)
@click.version_option(__version__, "-V", "--version", prog_name="spec-compile")
@click.argument(
    "bundle_dir",
    required=False,
    default=".",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
)
@click.option("--dry-run", is_flag=True, help="Parse + validate + show plan, don't call the LLM.")
@click.option(
    "--out",
    "out_override",
    default=None,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Override output.target.",
)
@click.option("--model", default=None, help="Override compiler.model.")
@click.option(
    "--engine",
    default=None,
    type=click.Choice(["openai", "anthropic", "local", "custom"], case_sensitive=False),
    help="Override compiler.engine.",
)
@click.option(
    "--record",
    "record_url",
    default=lambda: os.environ.get("SPEC_API"),
    help="Optionally POST a run record to a Spec Cloud instance.",
)
@click.option(
    "--record-token",
    default=lambda: os.environ.get("SPEC_TOKEN"),
    help="Bearer token for --record.",
)
def cli(
    bundle_dir: str,
    dry_run: bool,
    out_override: str | None,
    model: str | None,
    engine: str | None,
    record_url: str | None,
    record_token: str | None,
) -> None:
    """Compile a Spec bundle into generated code, locally."""
    root = Path(bundle_dir).resolve()
    opts = CompileOptions(
        dry_run=dry_run,
        out_override=Path(out_override).resolve() if out_override else None,
        model_override=model,
        engine_override=engine,
        record_url=record_url,
        record_token=record_token,
    )

    try:
        result = compile_bundle(root, opts)
    except SchemaError as e:
        err.print(f"[sf.reject]✗[/] manifest: {e}")
        sys.exit(2)
    except FrontmatterError as e:
        err.print(f"[sf.reject]✗[/] frontmatter: {e}")
        sys.exit(2)
    except BundleError as e:
        err.print(f"[sf.reject]✗[/] bundle: {e}")
        sys.exit(2)
    except EngineError as e:
        err.print(f"[sf.reject]✗[/] engine: {e}")
        sys.exit(3)
    except OutputError as e:
        err.print(f"[sf.reject]✗[/] output: {e}")
        sys.exit(4)

    b = result.bundle
    console.print(
        f"[sf.label]bundle[/] [bold]{b.manifest.name}[/] "
        f"[sf.muted]· {len(b.sources)} spec file(s), "
        f"{len(b.prompts)} prompt(s), "
        f"{len(result.groups)} group(s)[/]"
    )
    console.print(f"[sf.label]config[/] [sf.muted]{result.config_hash[:12]}…[/]")
    console.print()

    # Show the routing plan, group by group. This is the user's window into
    # "why is this file on this model?" — the same answer the Cloud UI pill
    # will show.
    for g in result.groups:
        cfg = g.config
        header = (
            f"[sf.point]{cfg.engine}[/]/[sf.point]{cfg.model}[/]  "
            f"[sf.muted]temp={cfg.temperature}  "
            f"max={cfg.max_output_tokens}  "
            f"· {len(g.members)} file(s)[/]"
        )
        console.print(header)
        for m in g.members:
            last = m.trail[-1]
            tail = "" if last.tier == "default" else f"  [sf.muted]({last.source})[/]"
            console.print(f"  [sf.muted]→[/] {m.path}{tail}")

    if result.dry_run:
        console.print()
        console.print("[sf.muted]--dry-run: no LLM call, no files written.[/]")
        return

    if not result.files:
        err.print("[sf.reject]✗[/] Compiler response contained no <file> blocks. Nothing written.")
        sys.exit(5)

    console.print()
    console.print(
        f"[sf.mint]✓[/] wrote {len(result.files)} file(s) → "
        f"[sf.point]{result.target}[/] "
        f"[sf.muted]({result.duration_ms} ms)[/]"
    )
    for f in result.files:
        console.print(f"  [sf.muted]·[/] {f.path}")
    console.print(f"[sf.label]output[/] [sf.muted]{result.output_hash[:12]}…[/]")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
