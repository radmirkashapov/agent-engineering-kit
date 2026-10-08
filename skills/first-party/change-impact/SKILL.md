---
version: 1
name: change-impact
description: Assess inbound and outbound change impact before implementation begins
policy: configurable
requires:
  model_capabilities:
    - reasoning
    - coding
    - tool_use
---

# Анализ влияния

Определи публичные контракты, вызывающие функции, потребителей, слой хранения и тесты. Для проекта из нескольких репозиториев пройди все компоненты из манифеста. В результате отдели подтверждённое влияние от гипотез.
