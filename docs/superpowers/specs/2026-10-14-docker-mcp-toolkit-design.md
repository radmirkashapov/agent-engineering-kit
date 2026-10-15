# Управляемый профиль Docker MCP Toolkit

## Назначение

Agent Engineering Kit поддерживает Docker MCP Toolkit как опциональный runtime для части MCP-серверов. Kit остаётся единственным источником истины для состава серверов, overrides, ACL, capability policy и активации по проектному контексту. Docker отвечает за контейнерный запуск, профиль, конфигурацию серверов и секреты.

Интеграция не добавляет Docker gateway как независимый девятый источник инструментов. Для каждого MCP ID выбирается ровно один способ доставки: нативная регистрация или профиль Docker.

## Предварительные условия

Интеграция использует официальный CLI:

```text
docker mcp profile create --name <profile>
docker mcp profile server add <profile> --server <uri>
docker mcp profile server remove <profile> --name <server>
docker mcp gateway run --profile <profile>
```

Требуется Docker Desktop с включённым MCP Toolkit. Если `docker mcp` отсутствует, обычные MCP продолжают работать, а Docker-команды Kit возвращают `CONFIG_REQUIRED` с понятной диагностикой.

## Конфигурация

Версионируемый файл `mcp/docker-toolkit.yaml` описывает только переносимый контракт:

- имя выделенного профиля `agent-engineering-kit`;
- режим по умолчанию `disabled`;
- основной Docker catalog;
- соответствие MCP ID и Docker server URI;
- поддерживаемые клиенты и имя gateway registration.

В базовой конфигурации используются только идентификаторы, подтверждённые официальной документацией Docker: `github-official` и `playwright`. Остальные MCP продолжают запускаться нативно, пока для них не появится явное mapping.

Локальные слои могут переопределять профиль, catalog URI и mappings:

```text
<data>/overrides/global/docker-toolkit.yaml
<data>/overrides/projects/<project-id>/docker-toolkit.yaml
```

Project override имеет приоритет над global override, а global — над committed default. Credentials и OAuth-данные в этих файлах запрещены.

## Команды

```text
agent-kit mcp docker status [--project <id-or-path>]
agent-kit mcp docker plan [--project <id-or-path>]
agent-kit mcp docker sync [--project <id-or-path>]
agent-kit mcp docker enable --scope global|project
agent-kit mcp docker disable --scope global|project
```

`status` проверяет наличие `docker mcp`, профиль, состав управляемых серверов, gateway и drift. Команда ничего не изменяет.

`plan` рассчитывает effective MCP, routing table и список Docker CLI операций. Секретные значения не выводятся.

`sync` явно применяет план к выделенному профилю. Команда создаёт отсутствующий профиль, добавляет нужные servers и удаляет только те servers, которые ранее были записаны Kit как управляемые. Неизвестные пользовательские записи сохраняются.

`enable` и `disable` меняют только локальный override выбранного scope и запускают обычный resync. Для project scope требуется logical project.

## Routing table и взаимное исключение

Для каждого effective MCP рассчитывается маршрут:

```text
blocked      — сервер запрещён effective policy;
docker       — сервер разрешён, Docker runtime включён и существует mapping;
native       — сервер разрешён, но Docker выключен или mapping отсутствует;
unavailable  — выбран Docker, но Toolkit не готов; до sync регистрация не переключается.
```

Переключение клиента выполняется только после успешного `sync`:

1. Kit проверяет состав выделенного Docker-профиля.
2. Сохраняет подтверждённый routing snapshot в machine-local state.
3. Исключает Docker-routed MCP из нативной регистрации клиента.
4. Регистрирует один namespaced gateway `agent-kit-docker` с командой `docker mcp gateway run --profile agent-engineering-kit`.
5. MCP без mapping сохраняют собственные нативные registrations.

При ошибке Docker profile не считается подтверждённым, текущая клиентская регистрация не переключается. Повторный `sync` идемпотентен.

## Владение состоянием

Kit хранит только:

- effective routing snapshot;
- список MCP, ранее добавленных Kit в Docker profile;
- результат последней сверки и версию конфигурации.

Состояние располагается в `<data>/state/docker-mcp-toolkit.json`. Нативные настройки Docker, OAuth и секреты не копируются в память проекта и не публикуются в Git.

Logical project влияет только на effective policy, overrides и project signals. Сам Docker profile остаётся machine-local.

## Безопасность

Capability policy применяется до выбора runtime. Запрещённый MCP не попадает в профиль Docker. Локальный override пользователя может изменить решение в соответствии с общей моделью свободы Kit.

Docker OAuth credentials разделяются между profiles, поэтому `doctor` обязан показывать это ограничение. Kit не экспортирует Docker profile автоматически и не записывает `.docker/mcp-profile.json` в проект.

Разрешены server URI со схемами `catalog://`, `docker://`, `https://` и `file://`. URI с userinfo, embedded credentials или небезопасным удалённым `http://` отклоняются.

## Ошибки и восстановление

- Нет команды `docker`: `NOT_INSTALLED`.
- Есть Docker, но нет `docker mcp`: `CONFIG_REQUIRED` с требованием обновить Docker Desktop и включить beta feature.
- Профиль отсутствует: `DRIFT`, план содержит `profile create`.
- Server mapping отсутствует: сервер остаётся `native`.
- Ошибка add/remove: `sync` прекращается, сохраняет незавершённое состояние и не меняет client routing.
- Состав профиля изменён вручную: `status` показывает drift, `plan` предлагает безопасное восстановление.

## Тестирование

Тесты используют fake command runner и не изменяют настоящий Docker Desktop.

Проверяются:

- отсутствие `docker mcp` без падения обычных MCP;
- слияние committed, global и project конфигурации;
- фильтрация effective MCP через capability policy;
- routing без дублирования native/Docker registrations;
- создание профиля, add/remove только управляемых servers и повторный idempotent sync;
- сохранение неизвестных записей профиля;
- отказ от URI с credentials;
- диагностика и русская документация;
- полный `pytest`, `agent-kit validate --ci` и `git diff --check`.

## Базовый набор MCP после реализации

Базовыми MCP Kit остаются:

1. `codebase-memory` — нативный.
2. `serena` — нативный.
3. `context7` — нативный remote MCP.
4. `github` — Docker mapping `github-official`, нативный fallback.
5. `gitlab` — нативный remote MCP.
6. `sonarqube` — нативный.
7. `playwright` — Docker mapping `playwright`, нативный fallback.
8. `atlassian` — нативный remote MCP.

`agent-kit-docker` не считается отдельным базовым MCP: это транспортный gateway для выбранных элементов списка.
