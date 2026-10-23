# OpenCode

OpenCode читает `AGENTS.md`, подключает skills через нативный поиск и загружает MCP из собственной конфигурации пользователя или проекта. Включите MCP в Kit командой `agent-kit mcp enable <id> --scope global`, затем вручную зарегистрируйте его в конфигурации OpenCode. Если проверка показывает `CONFIG_REQUIRED`, примените инструкцию регистрации и перезапустите OpenCode.

Перед запуском stdio MCP импортируйте необходимые значения: `agent-kit mcp creds import --from ./mcp-creds.env`. Проверьте импорт через `agent-kit mcp creds status`. При `AUTH_REQUIRED` устраните нехватку переменных для stdio сервера или завершите OAuth в текущем профиле OpenCode для remote MCP.

Atlassian, GitLab и Context7 требуют отдельного OAuth для каждого клиента или профиля. Общий Docker MCP Gateway допускает совместное использование несколькими клиентами; OAuth-состояние тогда хранится и обслуживается Docker Desktop. Никогда не вставляйте literal credentials в конфигурацию OpenCode или Git. Ротация выполняется повторным импортом и действует при следующем запуске MCP без `resync`; изменение определения или команды требует `agent-kit mcp enable <id> --scope global --resync`. `agent-kit mcp creds clear --yes` удаляет только machine-local хранилище Kit. После настройки выполните `agent-kit security scan`.

Источник: [skills в OpenCode](https://opencode.ai/docs/skills).
