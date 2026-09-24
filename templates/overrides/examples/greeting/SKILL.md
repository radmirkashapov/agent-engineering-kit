---
version: 1
name: greeting
description: Поздороваться с пользователем, назвав имя текущего пользователя системы
policy: configurable
requires:
  model_capabilities:
    - tool_use
---

# Динамическое приветствие

Запустите `scripts/greet.py` и верните пользователю его единственную строку вывода без изменений.
