---
version: 1
name: project-orientation
description: Определить логический проект, компоненты, документацию и итоговую конфигурацию
policy: configurable
requires:
  model_capabilities:
    - reasoning
    - tool_use
---

# Ориентация в проекте

Найди ближайший `.ai-team/project.yaml`, проверь `project.id`, репозитории и компоненты. Прочитай индекс документации, затем выполни `agent-kit config explain`. Корень Git не подменяет корень логического проекта.
