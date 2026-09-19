# ADR-0006: thin client adapters

Статус: принято.

## Контекст

Codex, Claude Code/Desktop, OpenCode и Cline используют разные native config, но policy не должна дублироваться.

## Решение

Tracked `adapter.yaml` описывает mapping к `AI.md`, skills и MCP. `agent-kit sync` materializes resolved absolute paths только в local runtime.

## Последствия

Client-specific glue остаётся малым. Native config и sessions принадлежат клиенту; некоторые клиенты требуют ручного подключения generated mapping.
