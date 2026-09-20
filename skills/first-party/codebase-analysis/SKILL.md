---
version: 1
name: codebase-analysis
description: Исследовать структуру и data/control flow с приоритетом code graph
policy: configurable
requires:
  model_capabilities:
    - reasoning
    - coding
    - tool_use
---

# Codebase analysis

Используй доступный code graph для definitions, calls и impact; text search — для literals/config или при неполном index. Сохраняй reusable выводы в project docs, временные observations — в local memory.
