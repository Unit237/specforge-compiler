---
spec:
  model: gpt-5
  temperature: 0.1
---

# Architecture overview

This file demonstrates two things:

1. It lives under `docs/architecture/` so the route `docs/architecture/**/*.md`
   matches — that would route it to `gpt-5` with `temperature: 0.15`.
2. The frontmatter block above explicitly overrides to `temperature: 0.1`
   because this particular document wants an even less wandering model.

Frontmatter wins over routes, which win over compiler defaults.
