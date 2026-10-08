---
version: 1
name: code-review
description: Review changes for defects, regressions, security risks, and missing tests
policy: configurable
requires:
  model_capabilities:
    - reasoning
    - coding
    - tool_use
---

# Проверка кода

Начни с изменённого контракта и проследи его потребителей. Замечания должны содержать серьёзность, место, способ воспроизведения или влияние и предлагаемое исправление. Не перечисляй стилистические предпочтения без соответствующего правила проекта.
