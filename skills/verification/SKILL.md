---
version: 1
id: verification
description: Доказать выполнение acceptance criteria воспроизводимыми проверками
policy: enforced
requires:
  model_capabilities:
    - reasoning
    - coding
    - tool_use
---

# Verification

Запусти targeted tests, затем repository validation и негативные cases. Запиши точные команды, exit codes и ограничения окружения. Mandatory validation нельзя отключить local override.
