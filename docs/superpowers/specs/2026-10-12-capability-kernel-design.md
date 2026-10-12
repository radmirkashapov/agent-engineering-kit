# Capability kernel, project topology и безопасная оркестрация

Статус: согласовано к реализации 12 октября 2026 года.

## Цель

Развить Agent Engineering Kit как независимый локальный control plane для нескольких AI-agent harness. Kit вычисляет effective policy, устанавливает общие роли, skills и MCP, проверяет conventions и технические инварианты, а execution loop оставляет выбранному клиенту.

## Границы системы

Система разделена на четыре уровня:

1. capability kernel загружает, объединяет, объясняет и проверяет конфигурацию;
2. client compiler материализует конфигурацию для внешнего harness;
3. внешний harness выполняет agent loop, обращения к модели и инструментам;
4. необязательный orchestrator управляет task workspace, worktree, проверками и интеграцией результатов.

`resync` не запускает задачи и не управляет worktree.

## Слои политики

Порядок применения от низшего приоритета к высшему:

1. значения поставщика;
2. общие настройки Kit;
3. корпоративный профиль;
4. необязательная конфигурация logical project;
5. глобальные локальные overrides;
6. локальные overrides проекта;
7. общие conventions Kit;
8. дополнительные conventions проекта;
9. технические инварианты.

Значения классифицируются как `preference`, `restriction` или `invariant`. Локальный пользователь может явно обойти `restriction`, включая ограничения моделей, ролей, skills, MCP, approvals, sandbox, сети и инструментов. `invariant` и conventions обойти нельзя.

Каждый override обязан иметь причину. Обход ограничения отражается в provenance, `config explain` и run manifest, но сам по себе не блокирует активацию.

## Глобальная и проектная конфигурация

Kit работает без продуктового проекта и устанавливает общие настройки разработчиков, тестировщиков и других ролей. Project manifest является необязательным opt-in слоем.

Версионируемый manifest может находиться в `.ai-team/project.yaml` продуктового или координационного репозитория. Когда менять репозиторий нельзя, descriptor хранится в `<data>/projects/<project-id>/project.yaml`, а локальные пути репозиториев — в machine-local bindings.

Project manifest задаёт стабильную идентичность, список репозиториев, настройки discovery, project conventions, требования к harness и память. Абсолютные пути и секреты в него не попадают.

## Память

Оперативная память хранится в `<data>/projects/<project-id>/` и включает `state`, `sessions`, `summaries`, `checkpoints`, `integrations`, `runs`, `tasks`, `worktrees` и `leases`. Она принадлежит машине, не коммитится и не является источником истины.

Каноническими знаниями остаются код, тесты, ADR и документация в Git. Между пользователями долговечные знания синхронизируются через Git, Pull Request и CI.

## Обнаружение структуры проекта

Компоненты не перечисляются вручную по умолчанию. Подключаемые discoverers анализируют build manifests и workspace metadata для Node.js, Maven, Gradle, Go, Cargo, .NET, Python и Bazel. Вычисленный inventory содержит стабильный ID, путь, тип, зависимости, evidence и confidence и сохраняется только в локальном state.

Project manifest хранит исключения и уточнения: ownership, criticality, дополнительные логические границы и исключённые пути.

Изменение workspace manifest получает отдельный признак `workspace-structure-change`, запускает повторный discovery и invalidation зависимых планов. Идентичность компонента строится из координат build system, а не только из пути.

## Multi-repository workspace

Logical project может включать несколько репозиториев. Версионируемый manifest содержит стабильные ID, безопасные remote без credentials, обязательность и компоненты. Machine-local bindings сопоставляют ID с фактическими путями.

Состояние проекта бывает `READY`, `DEGRADED`, `BLOCKED` или `MISMATCHED`. Отсутствующий обязательный репозиторий нельзя молча исключить из анализа. Возможность продолжить определяется областью влияния текущей задачи.

## Task workspace и worktree

Orchestrator создаёт task workspace с task ID, revision vector всех затронутых репозиториев, declared write set, worktree set, policy/conventions digests и run manifests.

Одна writable execution lane владеет одним worktree. Пересекающиеся write sets сериализуются. Интеграция выполняется в отдельном worktree через Git commits, merge или cherry-pick; файлы между worktree не копируются и не синхронизируются в реальном времени.

Локальные leases предотвращают конфликт на одной машине. Между машинами координацию обеспечивают remote branches, Pull Request, CI и merge queue.

## Документационный workflow

Conventions задают ownership для документации. Рабочие агенты объявляют write set и вместо конкурентного изменения горячих файлов создают уникальные change fragments. Documentation integrator единоразово обновляет `README.md`, `docs/INDEX.md` и другие канонические документы.

Новые ADR получают уникальные идентификаторы с датой и task ID. Принятый ADR не переписывается задним числом: новое решение создаёт ADR со связью `supersedes`. Индексы строятся детерминированно из metadata.

## Корпоративные MCP и данные

Корпоративные MCP поставляются доверенным каталогом или приватным policy repository. Записи описывают владельца, trust level, transport, способ авторизации, capabilities, допустимые классы данных, границы сети, режим чтения/записи, лимиты и аудит. Секреты хранятся только во внешнем secret broker, OAuth или native keychain.

Доступ разрешается на уровне capabilities, например `jira.issue.read`, `confluence.page.read` и `database.rows.sample`. Write/admin возможности выключены по умолчанию и требуют отдельного решения.

Результаты MCP считаются недоверенными данными, а не инструкциями. Правила требуют минимизации данных, защиты от prompt injection, совместимого model endpoint, redaction журналов, provenance, task-scoped доступа и очистки временных материалов.

## Run contract и наблюдаемость

Перед запуском создаётся `run-manifest/v1`: идентификатор запуска, ревизия Kit, project/workspace revision vector, digests policy и conventions, выбранный harness, capabilities, роли, skills, MCP, запрос модели, permission policy, Git/worktree и verification steps.

Фактические результаты записываются отдельно. Унифицированные события хранятся в JSONL; аргументы и результаты инструментов редактируются по политике. OpenTelemetry является необязательным exporter, а не обязательным хранилищем.

## Совместимость и внедрение

- Project manifest версии 1 остаётся валидным.
- Существующие команды skills и MCP становятся фасадами общего override engine.
- Текущие client adapters продолжают работать и постепенно получают проверяемые capability contracts.
- Codex служит первым reference adapter; остальные клиенты проверяются conformance tests.
- JEV/context optimization подключается только как экспериментальная capability после сравнительных evals.

## Критерии приёмки

- Kit работает глобально без project manifest.
- Local override может обойти restriction, но не invariant или convention.
- Project conventions и общие conventions проходят schema validation.
- Компоненты многомодульного проекта обнаруживаются автоматически.
- Multi-repo bindings и состояния готовности воспроизводимы.
- Run manifest и события не содержат секретов и сырых корпоративных данных.
- Корпоративные MCP имеют capability- и data-classification metadata.
- Task workspace обнаруживает пересекающиеся write sets и не изменяет основной checkout.
- Документационный workflow исключает неявное конкурентное изменение горячих файлов.
- Полный набор тестов, `agent-kit validate --ci` и проверки Git hygiene проходят успешно.
