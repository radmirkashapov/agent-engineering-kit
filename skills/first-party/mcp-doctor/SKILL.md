---
version: 1
name: mcp-doctor
description: Диагностировать MCP registration, transport, permissions и native state
policy: enforced
requires:
  model_capabilities:
    - reasoning
    - tool_use
---

# MCP doctor

Сверь registry и effective client config, доступность command/endpoint и только наличие нужных environment variables — никогда не печатай значения. Native MCP state не перемещай в project memory.
