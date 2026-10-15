---
version: 1
name: codebase-analysis
description: Analyze codebase structure, data flow, and control flow with graph-first discovery
policy: configurable
requires:
  model_capabilities:
    - reasoning
    - coding
    - tool_use
---

# Анализ кодовой базы

Используй доступный граф кода для определений, вызовов и анализа влияния; текстовый поиск — для строковых литералов, конфигурации или при неполном индексе. Сохраняй повторно используемые выводы в документации проекта, а временные наблюдения — в локальной памяти.
