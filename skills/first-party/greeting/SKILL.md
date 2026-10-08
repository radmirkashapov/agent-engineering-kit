---
version: 1
name: greeting
description: Greet the user with a short and neutral response
policy: configurable
requires:
  model_capabilities:
    - reasoning
---

# Приветствие

Если активная локальная реализация не заменила этот skill, ответьте точно: `Привет!`
