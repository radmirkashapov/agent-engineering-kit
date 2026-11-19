# OpenCode

OpenCode читает `AGENTS.md`, подключает skills через нативный поиск и загружает MCP из собственной конфигурации пользователя или проекта. Включите MCP в Kit командой `agent-kit mcp enable <id> --scope global --resync`: Kit автоматически объединит только `mcp.servers.agent-kit-*` в глобальном `~/.config/opencode/opencode.json`, либо в существующем `opencode.jsonc`. Пользовательские servers, providers, models и остальные поля сохраняются. Если проверка показывает `CONFIG_REQUIRED`, исправьте JSON/JSONC по указанному пути и повторите `resync`.

Пример для stdio Sentry (нужны Node.js/npm и заполненный `SENTRY_ACCESS_TOKEN` в локальном env-файле):

```bash
agent-kit mcp creds import --from ./mcp-creds.env
agent-kit mcp enable sentry --scope global --resync
agent-kit doctor
```

Запись `agent-kit-sentry` создаётся автоматически при `resync`; `agent-kit mcp launch-command sentry` нужен только для диагностики или ручного переноса. Список `command` уже содержит настоящий абсолютный executable и аргументы; поле `environment` с токенами не требуется. Генерация контракта не требует Codex или Claude Code. Data home фиксируется при импорте/генерации и доступен launcher даже без соответствующих переменных в окружении OpenCode. При переносе хранилища или смене команды повторите `resync`. Для другого MCP проверьте `agent-kit mcp available`: команда отказывает для выключенного сервера или запрещённого профилем доступа.

Формат локального сервера: [MCP servers в OpenCode](https://opencode.ai/docs/mcp-servers/).

Перед запуском stdio MCP импортируйте необходимые значения: `agent-kit mcp creds import --from ./mcp-creds.env`. Проверьте импорт через `agent-kit mcp creds status`. При `AUTH_REQUIRED` устраните нехватку переменных для stdio сервера или завершите OAuth в текущем профиле OpenCode для remote MCP.

GitLab и Context7 требуют отдельного OAuth для каждого клиента или профиля. Общий Docker MCP Gateway допускает совместное использование несколькими клиентами; OAuth-состояние тогда хранится и обслуживается Docker Desktop. Никогда не вставляйте literal credentials в конфигурацию OpenCode или Git. Ротация выполняется повторным импортом и действует при следующем запуске MCP без `resync`; изменение определения или команды требует `agent-kit mcp enable <id> --scope global --resync`. `agent-kit mcp creds clear --yes` удаляет только machine-local хранилище Kit. После настройки выполните `agent-kit security scan`.

Источник: [skills в OpenCode](https://opencode.ai/docs/skills).
