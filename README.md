# spec-compiler

> Local compiler that turns a Spec bundle of plain-English into real code.

Spec splits three surfaces on purpose:

1. **Spec Cloud** — stores bundles, diffs them, keeps the audit trail.
2. **Spec CLI** ([spec-cli](https://github.com/spec/spec-cli)) — syncs bundles with Cloud.
3. **Spec Compiler (this repo)** — runs **locally on your laptop**, reads a bundle, calls whatever model you configure, writes generated code to disk.

**The compiler is the only surface that talks to an LLM.** Cloud never calls
inference. Your API key, your model, your bill.

---

> **Most users don't need this.** `spec compile` in the CLI hands
> compilation to your running Claude Code session via a generated compile
> prompt — no API keys, no extra install. This package is what you reach
> for when you want the CLI to call an Anthropic / OpenAI / local model
> directly (`spec compile --via api`).

## Install

```bash
pip install 'spec-compiler[anthropic]'  # default engine — Claude
pip install 'spec-compiler[openai]'     # optional
pip install 'spec-compiler[all]'        # all of the above
```

Requires Python 3.9+.

## Quick start

```bash
cd examples/hello-world

export ANTHROPIC_API_KEY=sk-ant-...
spec-compile
# → writes out/hello.py and updates out/CHANGELOG.md
```

Or dry-run (no LLM call, just show the plan and config hash):

```bash
spec-compile --dry-run
```

## How it works

```
         spec.yaml
              │
              ▼
     ┌─────────────────┐
     │  parse manifest │  ← schema validation (strict, precise errors)
     └────────┬────────┘
              ▼
     ┌─────────────────┐
     │ walk spec files │  ← entry first, then include globs, then exclude
     └────────┬────────┘
              ▼
     ┌─────────────────┐
     │ assemble prompt │  ← prompts/*.md concatenated into the system msg
     └────────┬────────┘
              ▼
     ┌─────────────────┐
     │  engine.run()   │  ← openai | anthropic | local | custom
     └────────┬────────┘
              ▼
     ┌─────────────────┐
     │ parse <file>s   │  ← <file path="…">…</file> blocks
     └────────┬────────┘
              ▼
     ┌─────────────────┐
     │  write to disk  │  ← output.target, with path-escape guard
     └─────────────────┘
```

## Engines

| Engine | What it uses | Env |
|---|---|---|
| `openai` | `openai` SDK, chat completions | `OPENAI_API_KEY` |
| `anthropic` | `anthropic` SDK, messages API | `ANTHROPIC_API_KEY` |
| `local` | OpenAI-compatible HTTP endpoint (Ollama, LM Studio, llama.cpp) | `OPENAI_API_BASE` (defaults to Ollama's `http://localhost:11434/v1`) |
| `custom` | Your own HTTP endpoint — `POST {model, system, user, ...}` → `{"text": "..."}` | `SPEC_CUSTOM_ENGINE_URL` |

## Output contract

The compiler expects the model to emit files as `<file>` blocks:

```
<file path="src/hello.py">
def main():
    print("Hello")
</file>
```

Everything outside a `<file>` block is ignored as commentary. This format is
deliberately boring: it survives code that contains triple-backtick fences,
it stream-parses cleanly, and it's easy for any model to follow.

## Flags

```
spec-compile [BUNDLE_DIR]
  --dry-run                Parse + validate + show plan, don't call the LLM.
  --out <dir>              Override output.target.
  --model <name>           Override compiler.model.
  --engine <name>          Override compiler.engine.
  --record <url>           Optionally POST a run record to Spec Cloud.
  --record-token <token>   Bearer for --record.
```

`--record` sends Cloud **only** hashes and metadata (config hash, output
hash, file count, duration, engine, model) — never the raw generated code.
Keeps the audit trail without round-tripping the bill.

## The manifest (`spec.yaml`)

The schema lives in [`schema.py`](./src/spec_compiler/schema.py). `v0.1`:

```yaml
schema: "spec/v0.1"   # required
name: my-bundle             # required
description: …

spec:
  entry: docs/product.md    # compiled first
  include:                  # globs, top → bottom order matters
    - "docs/**/*.md"
  exclude: []

prompts:
  directory: prompts        # all .md under here form the system prompt

compiler:
  # defaults — used when nothing more specific matches. Claude-first
  # because `spec compile` (in the CLI) routes to Claude Code by
  # default, and you want both paths to land on the same model family.
  engine: anthropic         # anthropic | openai | local | custom
  model: claude-sonnet-4-5
  temperature: 0.2
  max_output_tokens: 8000

  # routes — first match wins, evaluated top-to-bottom
  routes:
    - match: "docs/architecture/**/*.md"
      model: claude-opus-4
      temperature: 0.15
    - match: "prompts/**/*.md"
      engine: anthropic
      model: claude-sonnet-4-5
    - match: "docs/**/*.md"
      model: claude-haiku-4

output:
  target: ./out
  changelog: true
  commit_style: conventional  # conventional | plain | none

approvals:
  required: 1

cloud:
  project: my-bundle        # optional binding to Spec Cloud
```

## Per-file model routing

Different docs want different models. An architecture brief wants a deep
reasoner; a boilerplate-spitting `run-tests.md` can run on something cheap.
Three tiers, resolved in this order:

1. **Frontmatter on the file.** A YAML block at the top of the `.md` under
   a `spec:` key wins over everything else.

   ```markdown
   ---
   spec:
     model: gpt-5
     temperature: 0.1
   ---
   # Billing migration — risk register
   ```

   Frontmatter outside the `spec:` key is ignored (Jekyll / Obsidian
   frontmatter is safe). Unknown keys *under* `spec:` are a hard error —
   typos should be loud.

2. **Route table in `spec.yaml`.** First match wins, evaluated top to
   bottom. Each route can override any `compiler.*` key.

3. **`compiler.*` defaults.** The fallback.

Files that resolve to the **same config are compiled in one LLM call** (one
big document, one response). Different configs produce separate calls. This
keeps cost proportional to routing, not file count.

The CLI shows the full plan on every run:

```
bundle billing · 30 spec file(s), 3 prompt(s), 3 group(s)
config f22725a11225…

openai/gpt-5  temp=0.15  max=8000  · 6 file(s)
  → docs/architecture/overview.md  (route:docs/architecture/**/*.md)
  → docs/architecture/events.md    (route:docs/architecture/**/*.md)
  …
anthropic/claude-sonnet-4  temp=0.2  max=8000  · 4 file(s)
  → prompts/scaffold.md            (route:prompts/**/*.md)
  …
openai/gpt-5-mini  temp=0.2  max=8000  · 20 file(s)
  → docs/auth/login.md             (route:docs/**/*.md)
  …
```

The `(route:…)` / `(frontmatter)` tag tells you exactly *why* each file is on
the model it's on. No tree-walking.

## Tests

```bash
pip install -e '.[dev]'
pytest
```

## License

MIT. See [LICENSE](./LICENSE).
