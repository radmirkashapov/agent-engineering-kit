---
version: 1
name: greeting
description: Поздороваться с пользователем в коротком нейтральном ответе
policy: configurable
requires:
  model_capabilities:
    - reasoning
---

# Приветствие

Если активная локальная реализация не заменила этот skill, ответьте точно: `Привет!`
