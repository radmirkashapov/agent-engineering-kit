---
version: 1
name: project-bootstrap
description: Инициализировать logical project без копирования глобальных rules
policy: configurable
requires:
  model_capabilities:
    - coding
    - tool_use
---

# Project bootstrap

1. Запусти `agent-kit project init <workspace>`.
2. Проверь найденные repositories и components в `.ai-team/project.yaml`.
3. Заполни `docs/INDEX.md` ссылками на существующие durable docs.
4. Запусти `agent-kit project status`.

Не размещай local memory, indexes или client sessions в project repository.
