# Cline

Cline получает rules, skills, MCP и корпоративный каталог моделей автоматически после `agent-kit resync`. Kit создаёт только `~/.cline/rules/agent-engineering-kit.md`, безопасно объединяет глобальный `~/.cline/data/settings/cline_mcp_settings.json` (Windows: `%USERPROFILE%\\.cline\\data\\settings\\cline_mcp_settings.json`) и публикует managed providers в `providers.json` вместе с `models.json`. Учитываются официальные переменные `CLINE_DIR`, `CLINE_DATA_DIR`, `CLINE_MCP_SETTINGS_PATH` и `CLINE_PROVIDER_SETTINGS_PATH`.

В JSON Kit владеет исключительно ключами `mcpServers.agent-kit-*`: устаревшие записи этого namespace удаляются, активные обновляются. Для provider из `models/corporate.yaml` Kit обновляет только provider с тем же ID и его managed model catalog: `baseUrl`, protocol и разрешённые модели. Другие providers, MCP, `global-settings.json`, sessions и пользовательские rules остаются без изменений. Для stdio серверов Cline запускает private launcher, поэтому token не записывается в settings JSON. `autoApprove` всегда остаётся пустым.

```bash
agent-kit mcp creds import --from ./mcp-creds.env
agent-kit mcp enable sentry --scope global --resync
agent-kit doctor
```

После синхронизации перезапустите Cline. Provider с `base_url` и моделями из effective corporate catalog появится в selector provider, а его модели — в selector моделей; вручную вводить model ID не требуется. Если ключ уже хранится в profile Cline, Kit сохраняет его. Если ключ отсутствует, но соответствующая `api_key_env` была импортирована командой `agent-kit models creds import`, Kit записывает его только в owner-only `providers.json` Cline. Remote OAuth для GitLab и Context7 по-прежнему завершается в Cline.

Практический порядок для разработчика простой: после обновления Kit перезапустите расширение, откройте настройки Cline, выберите корпоративный поставщик моделей и затем нужную модель из опубликованного списка. Если список не появился, сначала выполните `agent-kit resync`, проверьте `agent-kit models status`, а затем перезапустите Cline ещё раз. Не редактируйте внутренние файлы Cline вручную: Kit сохраняет пользовательский ключ и обновляет только сведения о корпоративном подключении.

Формат регистрации: [MCP в Cline](https://docs.cline.bot/mcp/mcp-overview).

Импортируйте credentials для stdio MCP через `agent-kit mcp creds import --from ./mcp-creds.env`, затем проверьте `agent-kit mcp creds status`. При `AUTH_REQUIRED` импортируйте отсутствующий токен и перезапустите сервер; для remote MCP выполните OAuth в текущем профиле Cline.

OAuth для GitLab и Context7 выполняется отдельно для каждого клиента и профиля. При намеренном использовании одного Docker MCP Gateway всеми клиентами OAuth-состоянием владеет Docker Desktop. Не сохраняйте literal credentials в Cline, правилах, проектных файлах или Git. Повторный импорт заменяет credential и применяется при следующем запуске MCP без `resync`; изменение определения или команды требует `agent-kit mcp enable <id> --scope global --resync`. Команда `agent-kit mcp creds clear --yes` удаляет только machine-local хранилище Kit. После настройки запустите `agent-kit security scan`.
