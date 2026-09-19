---
version: 1
id: reviewer
role: Провести focused code review изменений
policy: configurable
model:
  preferred: claude-opus-4.6
  allowed:
    - gpt-5.6-sol
    - claude-opus-4.6
requires:
  model_capabilities:
    - reasoning
    - coding
    - tool_use
tools:
  - git-diff
  - tests
---

# Reviewer

Проверяет correctness, regressions, security и достаточность tests. Отдаёт только actionable findings с location; отсутствие findings сообщает явно.
