---
version: 1
id: code-review
description: Проверить diff на defects, regressions, security и test gaps
policy: configurable
requires:
  model_capabilities:
    - reasoning
    - coding
    - tool_use
---

# Code review

Начни с изменённого contract и проследи его consumers. Findings должны иметь severity, location, reproduction/impact и предлагаемое исправление. Не перечисляй stylistic preferences без project rule.
