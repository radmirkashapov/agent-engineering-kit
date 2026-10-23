# Cline

Cline подключает `AGENTS.md`, Cline Rules и MCP через настройки расширения. Включите сервер командой `agent-kit mcp enable <id> --scope global`, затем вручную добавьте его в раздел MCP Servers в настройках Cline. При статусе `CONFIG_REQUIRED` следуйте подсказке Kit, сохраните сервер в настройках расширения и перезапустите Cline.

Импортируйте credentials для stdio MCP через `agent-kit mcp creds import --from ./mcp-creds.env`, затем проверьте `agent-kit mcp creds status`. При `AUTH_REQUIRED` импортируйте отсутствующий токен и перезапустите сервер; для remote MCP выполните OAuth в текущем профиле Cline.

OAuth для Atlassian, GitLab и Context7 выполняется отдельно для каждого клиента и профиля. При намеренном использовании одного Docker MCP Gateway всеми клиентами OAuth-состоянием владеет Docker Desktop. Не сохраняйте literal credentials в Cline, правилах, проектных файлах или Git. Повторный импорт заменяет credential и применяется при следующем запуске MCP без `resync`; изменение определения или команды требует `agent-kit mcp enable <id> --scope global --resync`. Команда `agent-kit mcp creds clear --yes` удаляет только machine-local хранилище Kit. После настройки запустите `agent-kit security scan`.
