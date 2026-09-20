---
version: 1
name: docs-index
description: Поддерживать docs/INDEX.md как карту canonical durable knowledge
policy: configurable
requires:
  model_capabilities:
    - reasoning
---

# Docs index

Обновляй индекс при появлении ADR, architecture docs и runbooks. Ссылки должны быть относительными и проверяемыми. Mutable session summaries не считаются authoritative documentation.
