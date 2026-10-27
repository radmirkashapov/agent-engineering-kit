# Результаты smoke-проверки

Проверка выполнена во временном проекте в macOS-среде. Она подтверждает основные локальные сценарии и показывает состояния интеграций, которые требуют отдельных credentials или включённых MCP. Результаты не означают, что внешние GitHub, GitLab, Jira или PR-сервисы подключались.

## Успешно проверено

- Временный проект создан командой `agent-kit project init <path> --git`; обнаружение, сверка состава с `project reconcile <PATH>` и `project reconcile <PATH> --apply`, состояние проекта и `config explain` завершились успешно.
- Временный Git-репозиторий принял локальный commit и push в bare remote. Для этого не требовались GitHub, GitLab или Jira.
- Справка по `project`, `task`, `config` и `security`, а также `skills list`, `mcp list`, `security status`, `validate --ci`, `doctor`, `security doctor` и `resync --no-update` прошли smoke-проверку.
- `override list --scope project` и `override list --scope global` показали пустые списки.
- `agent-kit mcp creds status` корректно показала отсутствующие токены GitHub, Sentry и SonarQube; `SENTRY_HOST` необязателен.
- Справка `pr refresh --help` проверена; саму интеграцию намеренно не запускали.

## Задачи и блокировки

Команда `agent-kit task create SOME-42 --type feat --summary local-smoke --write 'src/**'` создала ветку `feat/27-10-2026-some-42-local-smoke` и рабочее дерево; проверка `status` и `lease` прошла.

Короткая команда `agent task create` поддерживает создание задачи и lane, но не статус и не параметр `--summary`. Команда `agent task create DEMO-7 --type docs --write 'docs/**'` прошла успешно. Задача DEMO-8 с тем же write set перешла в `WAITING`, а `blocked_by` указал на DEMO-7. В проверке двух lanes `worker-a` получила состояние `active`, `worker-b` — `waiting` из-за пересекающихся write sets.

## Особенность завершения task workspace

Для временного workspace, чей project ID не разрешается как подключённый logical project, команда `agent-kit task complete agent-kit-smoke-pekjpg <TASK>` фактически записала терминальный статус `completed`, затем завершилась с ошибкой `Logical project не найден: agent-kit-smoke-pekjpg` при последующем обновлении памяти. Это воспроизводимое поведение команды после завершения workspace, а не ошибка очистки: отдельный `release` после этого прошёл.

В таком случае проверьте `agent-kit task status <TASK>`, затем выполните `agent-kit task release <project-id> <TASK>`. Если у задачи есть управляемые рабочие деревья, удалите их штатным Git-worktree workflow до `agent-kit task gc <project-id> <TASK>`. Для обычного подключённого проекта убедитесь, что `project.id` совпадает с ID workspace, прежде чем завершать задачу.

## Интеграции, требующие настройки

Команды `doctor` и `resync --no-update` показали ожидаемые статусы `CONFIG_REQUIRED` и `AUTH_REQUIRED` для Context7, которому не хватало настройки и авторизации. Это диагностические состояния интеграции, а не ошибка установки CLI. Для Context7 требуется пройти OAuth в выбранном клиенте и профиле.

Команда `agent-kit project skills status` вернула `NOT_CONFIGURED` и код выхода 1: в проверяемом проекте источник project-skills не был настроен. Это ожидаемое состояние для проекта без такого источника.

Команда `agent-kit project memory-refresh` завершилась с кодом 0, но сообщила `SKIPPED` для Codebase Memory и Serena, потому что соответствующие MCP отключены или их исполняемые файлы недоступны. Код 0 в этом случае не означает, что индексы построены. После настройки MCP запустите обновление повторно.

## Security scan: нужен ручной разбор

Общая команда `security scan` завершилась со статусом `FAIL`. Инвентаризация проекта через Bumblebee прошла: 0 findings в 6 файлах. First-party skills также прошли проверку. Отдельно сканер сообщил статические findings во внешних навыках из набора Superpowers:

| Skill | Число findings |
|---|---:|
| `brainstorming` | 10 |
| `subagent-driven-development` | 8 |
| `systematic-debugging` | 4 |
| `writing-skills` | 24 |

Кроме того, для semantic analyzers отсутствовали API keys. Эти результаты требуют ручного просмотра findings и настройки ключей, если нужны semantic-проверки. Их нельзя трактовать как чистый результат, но они также сами по себе не показывают сбой установки Agent Engineering Kit.

Пока findings не рассмотрены, не считайте проверенные сторонние навыки безопасными для активации. Подробности сканеров и безопасного обращения с их выводом описаны в разделе [security scan](Security-and-PR).
