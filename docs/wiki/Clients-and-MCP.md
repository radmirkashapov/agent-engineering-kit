# Клиенты, MCP и credentials

Kit подключает общие правила, skills и MCP к нескольким AI-клиентам, но не управляет одинаково всеми функциями каждого клиента.

## Поддерживаемые клиенты

В репозитории есть адаптеры и договоры возможностей для `Codex` / `Codex Desktop`, `Claude Code`, `Claude Desktop`, `OpenCode` и `Cline`. Команда `agent-kit config explain` показывает выбранный клиент и происхождение итоговых настроек. Часть интеграций создаётся автоматически; для графических клиентов может потребоваться ручная регистрация. Подробные инструкции находятся в каталоге `clients/` и разделе [адаптеров в README](https://github.com/radmirkashapov/agent-engineering-kit/blob/main/README.md#адаптеры-клиентов).

## Назначение и маршрутизация MCP

| MCP | Для чего использовать |
|---|---|
| Codebase Memory | Граф кода, вызовы, архитектура и impact analysis |
| Serena | Символы, ссылки и семантическое редактирование |
| Context7 | Текущая внешняя документация библиотек и API |
| Sentry | Read-only исследование ошибок и release health; выключен по умолчанию |
| GitHub / GitLab | Контекст соответствующего SCM и PR/MR |
| Playwright | Браузер для веб-проектов |
| SonarQube | Существующие серверные замечания качества |
| Atlassian | Контекст Jira и Confluence при настроенном проекте |

Условные интеграции выбираются по признакам проекта. Сервер регистрируется целиком только в том случае, если клиент применяет весь объявленный набор возможностей. Поэтому профиль только для чтения может отключить сервер, совмещающий чтение и запись, если клиент не умеет ограничить набор инструментов.

Codebase Memory и Serena дополняют друг друга: сначала граф помогает определить область влияния, затем Serena уточняет конкретные символы. Не запускайте широкий поиск обоими средствами без необходимости.

Docker MCP Toolkit — опциональный runtime для поддерживаемых серверов. Kit управляет выделенным профилем agent-engineering-kit. Перед переключением используйте agent-kit mcp docker plan, затем sync. До успешного sync текущая регистрация не переключается.

## Credentials и OAuth

Для stdio MCP скопируйте пример env-файла и импортируйте значения в machine-local vault:

```bash
cp mcp-creds.example.env mcp-creds.env
# Заполнить только нужные переменные.
agent-kit mcp creds import --from ./mcp-creds.env
agent-kit mcp creds status
agent-kit mcp enable github --scope global --resync
```

В Git и конфигурациях хранятся только ссылки env:VARIABLE или имена переменных; secret values не помещают в YAML, client config, командную строку или отчёты. Vault принадлежит Kit, а OAuth-состояние принадлежит клиенту.

Удалённая авторизация OAuth проходит в конкретном клиенте и профиле. Авторизация Atlassian, GitLab и Context7 не переносится автоматически между клиентами. При `AUTH_REQUIRED` сначала проверьте `agent-kit mcp creds status`; для stdio импортируйте недостающие переменные и перезапустите клиент, для удалённого MCP завершите OAuth в соответствующем профиле. Smoke-проверка показала, что токены GitHub, Sentry и SonarQube отсутствовали; `SENTRY_HOST` при этом необязателен.

agent-kit mcp launch-command <id> создаёт JSON command/args для ручной регистрации включённого stdio MCP. Команда учитывает текущий профиль доступа; remote OAuth она не заменяет.

Подробное описание MCP и безопасной загрузки учётных данных доступно в [руководстве по MCP](https://github.com/radmirkashapov/agent-engineering-kit/blob/main/mcp/README.md) и [дизайне загрузки credentials](https://github.com/radmirkashapov/agent-engineering-kit/blob/main/docs/superpowers/specs/2026-10-23-mcp-credentials-design.md). См. также [профили и роли](Profiles-and-roles).
