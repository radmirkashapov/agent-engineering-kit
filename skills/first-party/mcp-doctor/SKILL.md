---
version: 1
name: mcp-doctor
description: Diagnose MCP registration, transport, permissions, and client-native state
policy: enforced
requires:
  model_capabilities:
    - reasoning
    - tool_use
---

# Диагностика MCP

Сверь реестр и итоговую конфигурацию клиента, доступность команды или конечной точки и только наличие нужных переменных окружения — никогда не печатай их значения. Нативное состояние MCP не перемещай в память проекта.
