# Cline

Cline подключает `AGENTS.md`, Cline Rules и MCP через настройки расширения. Включите сервер командой `agent-kit mcp enable <id> --scope global`, затем вручную добавьте его в раздел MCP Servers в настройках Cline. При статусе `CONFIG_REQUIRED` следуйте подсказке Kit, сохраните сервер в настройках расширения и перезапустите Cline.

Пример для stdio Sentry (нужны Node.js/npm и локальный env-файл с `SENTRY_ACCESS_TOKEN`):

```bash
agent-kit mcp creds import --from ./mcp-creds.env
agent-kit mcp enable sentry --scope global
agent-kit resync --no-update
agent-kit mcp launch-command sentry | python3 -c 'import json,sys; r=json.load(sys.stdin); r.update(disabled=False, autoApprove=[]); print(json.dumps({"mcpServers": {"agent-kit-sentry": r}}, indent=2))'
```

В панели Cline откройте MCP Servers → Configure → Configure MCP Servers. Объедините выведенную запись `mcpServers.agent-kit-sentry` с открытым `cline_mcp_settings.json`, сохраните и перезапустите сервер. Команда выводит реальные абсолютные `command`/`args`; поле `env` не требуется. Codex и Claude Code для генерации не нужны. Launcher использует data home, выбранный при генерации, даже если Cline не наследует переменные shell. После переноса vault или смены команды заново сгенерируйте и замените запись. Для другого MCP проверьте разрешение текущего профиля через `agent-kit mcp available`.

Формат регистрации: [MCP в Cline](https://docs.cline.bot/mcp/mcp-overview).

Импортируйте credentials для stdio MCP через `agent-kit mcp creds import --from ./mcp-creds.env`, затем проверьте `agent-kit mcp creds status`. При `AUTH_REQUIRED` импортируйте отсутствующий токен и перезапустите сервер; для remote MCP выполните OAuth в текущем профиле Cline.

OAuth для Atlassian, GitLab и Context7 выполняется отдельно для каждого клиента и профиля. При намеренном использовании одного Docker MCP Gateway всеми клиентами OAuth-состоянием владеет Docker Desktop. Не сохраняйте literal credentials в Cline, правилах, проектных файлах или Git. Повторный импорт заменяет credential и применяется при следующем запуске MCP без `resync`; изменение определения или команды требует `agent-kit mcp enable <id> --scope global --resync`. Команда `agent-kit mcp creds clear --yes` удаляет только machine-local хранилище Kit. После настройки запустите `agent-kit security scan`.
