# Claude Code

Инструкции подключаются через `~/.claude/CLAUDE.md`, skills — через `~/.claude/skills`, а MCP регистрируется в пользовательской конфигурации `~/.claude.json`. Включайте сервер командой `agent-kit mcp enable <id> --scope global --resync`; Kit автоматически регистрирует поддерживаемый launcher.

Перед запуском stdio MCP импортируйте нужные значения: `agent-kit mcp creds import --from ./mcp-creds.env`. Проверьте их наличие через `agent-kit mcp creds status`. При `AUTH_REQUIRED` исправьте отсутствующие stdio credentials или завершите OAuth в текущем профиле Claude Code для remote MCP, затем перезапустите сервер.

OAuth для Atlassian, GitLab и Context7 относится к отдельному клиенту и профилю. Если все клиенты используют один Docker MCP Gateway, OAuth-состоянием владеет Docker Desktop. Не помещайте literal credentials в `~/.claude.json`, проектные файлы или Git. Ротация выполняется повторным импортом и применяется со следующим запуском MCP без `resync`; изменения определения или команды требуют `resync`. Команда `agent-kit mcp creds clear --yes` очищает только machine-local хранилище Kit. После настройки выполните `agent-kit security scan`.

Источник: [каталоги Claude Code](https://code.claude.com/docs/en/claude-directory).
