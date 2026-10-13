---
version: 1
name: greeting
description: Greet the user by including the current operating-system account name
policy: configurable
requires:
  model_capabilities:
    - tool_use
---

# Динамическое приветствие

Запустите `scripts/greet.py` и верните пользователю его единственную строку вывода без изменений.
