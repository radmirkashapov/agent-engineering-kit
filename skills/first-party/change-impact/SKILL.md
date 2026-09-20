---
version: 1
name: change-impact
description: Оценить inbound/outbound impact изменения до реализации
policy: configurable
requires:
  model_capabilities:
    - reasoning
    - coding
    - tool_use
---

# Change impact

Определи public contracts, callers, consumers, persistence и tests. Для multi-repo project пройди все components из manifest. Результат должен разделять confirmed impact и hypotheses.
