# Claude Desktop

Claude Desktop управляет MCP отдельно от Claude Code. Включите нужный сервер через `agent-kit mcp enable <id> --scope global`, затем вручную зарегистрируйте его в Claude Desktop через Settings → Developer → Edit Config (`claude_desktop_config.json`). Если Kit сообщает `CONFIG_REQUIRED`, завершите регистрацию по показанной инструкции клиента и перезапустите Desktop.

После сохранения конфигурации проверьте, что сервер появился в списке подключений Desktop. Настройки другого клиента не создают такую регистрацию автоматически.

Пример для stdio Sentry (нужны Node.js/npm и импортированный `SENTRY_ACCESS_TOKEN` из шаблона):

```bash
agent-kit mcp creds import --from ./mcp-creds.env
agent-kit mcp enable sentry --scope global
agent-kit resync --no-update
agent-kit mcp launch-command sentry | python3 -c 'import json,sys; print(json.dumps({"mcpServers": {"agent-kit-sentry": json.load(sys.stdin)}}, indent=2))'
```

Последняя команда генерирует готовый JSON с реальными абсолютными путями этой машины. Перенесите запись `agent-kit-sentry` в `mcpServers` файла `claude_desktop_config.json`, открытого через Settings → Developer → Edit Config; объедините её с существующими записями и перезапустите Desktop. Поле `env` заполнять не нужно. Codex и Claude Code не требуются. Если используется иной data home, задайте его при импорте и генерации; контракт запомнит путь, даже если GUI не получает эти переменные. При изменении data home или команды сервера повторите генерацию и обновите запись. Для GitHub и других MCP сначала убедитесь через `agent-kit mcp available`, что текущий профиль разрешает весь surface сервера.

Формат регистрации: [подключение локального MCP в Claude Desktop](https://modelcontextprotocol.io/docs/develop/connect-local-servers).

Для stdio MCP импортируйте значения командой `agent-kit mcp creds import --from ./mcp-creds.env` и проверьте `agent-kit mcp creds status`. При `AUTH_REQUIRED` добавьте недостающие credentials в machine-local хранилище Kit и перезапустите Desktop. Для remote MCP завершите OAuth в самом Claude Desktop и повторите запрос.

OAuth для Atlassian, GitLab и Context7 необходимо выполнять отдельно для каждого клиента и профиля. Если несколько клиентов используют один Docker MCP Gateway, владельцем OAuth-состояния становится Docker Desktop. Не записывайте literal credentials в `claude_desktop_config.json` или другие нативные настройки. Повторный импорт ротирует значение без `resync` и применяется при следующем запуске MCP; изменение определения или команды требует `agent-kit mcp enable <id> --scope global --resync`. `agent-kit mcp creds clear --yes` очищает только machine-local хранилище Kit. После настройки запустите `agent-kit security scan`.
