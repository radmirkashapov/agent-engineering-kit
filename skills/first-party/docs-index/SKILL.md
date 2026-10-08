---
version: 1
name: docs-index
description: Maintain docs/INDEX.md as the map of canonical durable project knowledge
policy: configurable
requires:
  model_capabilities:
    - reasoning
---

# Индекс документации

Обновляй индекс при появлении ADR, архитектурной документации и эксплуатационных инструкций. Ссылки должны быть относительными и проверяемыми. Изменяемые сводки сеанса не считаются авторитетной документацией.
