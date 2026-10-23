# Codex CLI и Codex Desktop

CLI и Desktop используют общее MCP-пространство Codex в `~/.codex/config.toml`. Включайте сервер командой `agent-kit mcp enable <id> --scope global --resync`; Kit автоматически регистрирует поддерживаемые серверы через launcher. Инструкции и skills подключаются отдельно через `~/.codex/AGENTS.md` и `~/.agents/skills`.

Для stdio credentials импортируйте нужные значения из `mcp-creds.env` командой `agent-kit mcp creds import --from ./mcp-creds.env`, затем проверьте `agent-kit mcp creds status`. Если Codex показывает `AUTH_REQUIRED`, проверьте состояние stdio credentials; для remote MCP завершите OAuth в активном Codex-профиле и повторите запрос.

OAuth для Atlassian, GitLab и Context7 выполняется отдельно в каждом клиенте или профиле. Все клиенты могут намеренно использовать один Docker MCP Gateway; тогда OAuth-состояние принадлежит Docker Desktop. Не вставляйте literal credentials в `config.toml` или другие нативные настройки. Ротация выполняется повторным импортом и применяется при следующем запуске MCP без `resync`; изменение определения или команды требует `resync`. `agent-kit mcp creds clear --yes` удаляет только machine-local хранилище Kit. После настройки запустите `agent-kit security scan`.

Источники: [инструкции AGENTS.md](https://developers.openai.com/docs/agent-configuration/agents-md), [MCP](https://developers.openai.com/docs/extend/mcp), [Skills](https://developers.openai.com/docs/build-skills).
