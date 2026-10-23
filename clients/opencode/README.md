# OpenCode

OpenCode читает `AGENTS.md`, подключает skills через нативный поиск и загружает MCP из собственной конфигурации пользователя или проекта. Включите MCP в Kit командой `agent-kit mcp enable <id> --scope global`, затем вручную зарегистрируйте его в конфигурации OpenCode. Если проверка показывает `CONFIG_REQUIRED`, примените инструкцию регистрации и перезапустите OpenCode.

Пример для stdio Sentry (нужны Node.js/npm и заполненный `SENTRY_ACCESS_TOKEN` в локальном env-файле):

```bash
agent-kit mcp creds import --from ./mcp-creds.env
agent-kit mcp enable sentry --scope global
agent-kit resync --no-update
agent-kit mcp launch-command sentry | python3 -c 'import json,sys; r=json.load(sys.stdin); print(json.dumps({"mcp": {"agent-kit-sentry": {"type": "local", "command": [r["command"], *r["args"]], "enabled": True}}}, indent=2))'
```

Объедините полученный объект `mcp.agent-kit-sentry` с конфигурацией `opencode.json`/`opencode.jsonc` проекта либо пользовательской конфигурацией OpenCode и перезапустите клиент. Список `command` уже содержит настоящий абсолютный executable и аргументы; поле `environment` с токенами не требуется. Генерация контракта не требует Codex или Claude Code. Data home фиксируется при импорте/генерации и доступен launcher даже без соответствующих переменных в окружении OpenCode. При переносе хранилища или смене команды повторите генерацию. Для другого MCP проверьте `agent-kit mcp available`: команда отказывает для выключенного сервера или запрещённого профилем доступа.

Формат локального сервера: [MCP servers в OpenCode](https://opencode.ai/docs/mcp-servers/).

Перед запуском stdio MCP импортируйте необходимые значения: `agent-kit mcp creds import --from ./mcp-creds.env`. Проверьте импорт через `agent-kit mcp creds status`. При `AUTH_REQUIRED` устраните нехватку переменных для stdio сервера или завершите OAuth в текущем профиле OpenCode для remote MCP.

Atlassian, GitLab и Context7 требуют отдельного OAuth для каждого клиента или профиля. Общий Docker MCP Gateway допускает совместное использование несколькими клиентами; OAuth-состояние тогда хранится и обслуживается Docker Desktop. Никогда не вставляйте literal credentials в конфигурацию OpenCode или Git. Ротация выполняется повторным импортом и действует при следующем запуске MCP без `resync`; изменение определения или команды требует `agent-kit mcp enable <id> --scope global --resync`. `agent-kit mcp creds clear --yes` удаляет только machine-local хранилище Kit. После настройки выполните `agent-kit security scan`.

Источник: [skills в OpenCode](https://opencode.ai/docs/skills).
