---
version: 1
name: project-bootstrap
description: Initialize a logical project without copying global rules into its repository
policy: configurable
requires:
  model_capabilities:
    - coding
    - tool_use
---

# Инициализация проекта

1. Запусти `agent-kit project init <workspace>`.
2. Проверь найденные репозитории и компоненты в `.ai-team/project.yaml`.
3. Заполни `docs/INDEX.md` ссылками на существующую долговечную документацию.
4. Запусти `agent-kit project status`.

Не размещай локальную память, индексы или сеансы клиентов в репозитории проекта.
