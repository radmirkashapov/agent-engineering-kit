# Cline

Cline получает rules, skills и MCP автоматически после `agent-kit resync`. Kit создаёт только `~/.cline/rules/agent-engineering-kit.md` и безопасно объединяет глобальный `~/.cline/data/settings/cline_mcp_settings.json` (Windows: `%USERPROFILE%\\.cline\\data\\settings\\cline_mcp_settings.json`). Учитываются официальные переменные `CLINE_DIR`, `CLINE_DATA_DIR` и `CLINE_MCP_SETTINGS_PATH`.

В JSON Kit владеет исключительно ключами `mcpServers.agent-kit-*`: устаревшие записи этого namespace удаляются, активные обновляются. Все остальные MCP, `providers.json`, `global-settings.json`, sessions и пользовательские rules остаются без изменений. Для stdio серверов Cline запускает private launcher, поэтому token не записывается в settings JSON. `autoApprove` всегда остаётся пустым.

```bash
agent-kit mcp creds import --from ./mcp-creds.env
agent-kit mcp enable sentry --scope global --resync
agent-kit doctor
```

После синхронизации перезапустите Cline либо перезапустите сервер в панели MCP Servers. Remote OAuth для GitLab и Context7 по-прежнему завершается в Cline. Модели и provider Cline не синхронизируются: Cline хранит их во внутреннем state с секретами, для которого Kit не использует нестабильный формат; настройте provider через UI или `cline auth`.

Формат регистрации: [MCP в Cline](https://docs.cline.bot/mcp/mcp-overview).

Импортируйте credentials для stdio MCP через `agent-kit mcp creds import --from ./mcp-creds.env`, затем проверьте `agent-kit mcp creds status`. При `AUTH_REQUIRED` импортируйте отсутствующий токен и перезапустите сервер; для remote MCP выполните OAuth в текущем профиле Cline.

OAuth для GitLab и Context7 выполняется отдельно для каждого клиента и профиля. При намеренном использовании одного Docker MCP Gateway всеми клиентами OAuth-состоянием владеет Docker Desktop. Не сохраняйте literal credentials в Cline, правилах, проектных файлах или Git. Повторный импорт заменяет credential и применяется при следующем запуске MCP без `resync`; изменение определения или команды требует `agent-kit mcp enable <id> --scope global --resync`. Команда `agent-kit mcp creds clear --yes` удаляет только machine-local хранилище Kit. После настройки запустите `agent-kit security scan`.
