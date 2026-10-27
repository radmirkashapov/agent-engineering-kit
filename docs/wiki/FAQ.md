# Частые вопросы

## Kit запускает AI-агента?

Нет. Kit формирует policy и конфигурацию для внешнего harness. Агентный цикл, контекст, sandbox, approvals и события принадлежат клиенту. Подробнее — в [обзоре](Overview).

## Нужен ли .ai-team/project.yaml?

Нет для общих настроек. Manifest помогает описывать компоненты, несколько repositories, соглашения и интеграции. Если repository нельзя менять, используйте machine-local project attach.

## Где лежат память и индексы?

В локальных каталогах машины и нативных data directories MCP. Они не коммитятся вместе с product repository.

## Lease работает между компьютерами?

Нет. Lease защищает от пересекающихся write sets на одной машине. Между ПК используйте Git branches, PR/MR, CI и merge queue.

## Почему read-only профиль может не запускать MCP?

Если сервер содержит mixed read/write tools, клиент должен ограничить весь capability contract. Без этой возможности Kit отключает нативную регистрацию целиком, а не объявляет сервер read-only.

## Где хранить credentials?

В machine-local vault Kit или в нативном OAuth конкретного клиента. Не добавляйте значения в YAML, Git или командную строку. См. [credentials и MCP](Clients-and-MCP).

## Можно ли локально отключить enforced skill или MCP?

Владелец машины может изменить effective-конфигурацию через локальный override. Это не меняет корпоративные файлы Git и CI-проверки переносимого репозитория. См. [overrides](Overrides).

## Как узнать точные аргументы команды?

Выполните `agent-kit help <path>` или `agent-kit <path> --help`. Команды проверены в smoke-тесте; учтите ограничения короткой команды `agent task`, описанные в [справочнике CLI](CLI) и [результатах проверки](Smoke-test).

## Где полная документация?

Читайте [README](https://github.com/radmirkashapov/agent-engineering-kit/blob/main/README.md), [docs/INDEX.md](https://github.com/radmirkashapov/agent-engineering-kit/blob/main/docs/INDEX.md), [главную страницу Wiki](Home) и [корпоративный runbook](https://github.com/radmirkashapov/agent-engineering-kit/blob/main/docs/runbooks/install-from-gitlab-fork.md).
