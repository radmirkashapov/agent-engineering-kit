---
version: 1
name: verification
description: Prove acceptance criteria with reproducible verification evidence
policy: enforced
requires:
  model_capabilities:
    - reasoning
    - coding
    - tool_use
---

# Проверка результата

Запусти целевые тесты, затем проверку репозитория и негативные сценарии. Запиши точные команды, коды завершения и ограничения окружения. Обязательную проверку нельзя отключить локальным переопределением.
