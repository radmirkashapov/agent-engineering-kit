# agent-engineering-kit

## Что это

`agent-engineering-kit` — единый локальный набор правил, навыков (skills), ролей агентов, MCP и адаптеров для AI-клиентов разработки. Один экземпляр набора обслуживает на машине несколько независимых логических проектов.

```text
одна машина → один agent-engineering-kit → несколько логических проектов
```

Набор является управляющим слоем. Git-репозиторий Kit не хранит память проектов, учётные данные, сеансы, базы MCP или пользовательские настройки: локальное состояние размещается в каталоге данных машины и отделено от версионируемых определений.

## Быстрый старт

```bash
# Установить CLI из рабочей копии Kit.
./bootstrap/install.sh

# Проверить переносимую конфигурацию и подготовить локальное окружение.
agent-kit validate --ci
agent-kit resync --no-update
agent-kit doctor

# Открыть встроенную справку.
agent-kit help
```

Для подключения продуктового репозитория перейдите в его корень и выполните:

```bash
agent-kit project init
agent-kit project status .
agent-kit config explain .
```

Kit не заменяет Git, Pull Request, CI или выбранный AI-клиент. Он формирует согласованную конфигурацию, а разработка, commit, push и PR выполняются штатными средствами Git и платформы репозитория.

## Связь с agent harness

`agent-engineering-kit` — control plane и компилятор эффективной политики, а не собственный agent runtime. Он определяет роли, rules, skills, MCP, модели, локальные overrides и способы подключения клиентов. Цикл агента, контекстное окно, sandbox, approvals, жизненный цикл задач и поток событий остаются ответственностью внешнего execution harness: Codex, Claude Code, Claude Desktop, OpenCode или Cline.

`catalog/clients.yaml` содержит проверяемый capability contract каждого адаптера. В нём отдельно перечислены возможности, которыми управляет Kit, и возможности, делегированные клиенту. `agent-kit config explain` показывает выбранный harness, а `resync` записывает контракт и хеш эффективной политики в локальный `effective-environment.json`.

Kit уже формирует контракты запусков, task workspace, leases и планы managed worktree. Само выполнение задач, очереди, повторные запуски и создание Pull Request остаются обязанностью внешнего harness или отдельного необязательного orchestrator.

## Карта репозитория

| Путь | Назначение и связи | Как переиспользовать |
|---|---|---|
| `agents/` | Переносимые определения ролей; ссылаются на rules, skills и модельные требования. | Выбрать роль через профиль или подключить к адаптеру клиента. |
| `rules/` | Общие инженерные, Git-, security- и data-handling правила. | Подключать как канонический слой, не копируя в продуктовый репозиторий. |
| `conventions/` | Необходимые соглашения о структуре, документации и рабочем процессе. | Дополнять проектными YAML из `.ai-team/project.yaml`; существующие ID не переопределяются. |
| `profiles/` | Профили разработчика, тестировщика и рецензента с ролями и разрешениями. | Компилировать в capability contract выбранного harness. |
| `skills/first-party/` | Skills самого Kit; сторонние skills здесь не vendoring-ятся. | Подключать через общий каталог discovery клиента. |
| `mcp/` | Желаемое состояние MCP и инструкция по эксплуатации. | Устанавливать и регистрировать через `resync`; доступ определяет capability policy. |
| `catalog/` | Каталоги клиентов, внешних skills, корпоративных MCP и классов данных. | Расширять декларативно с обязательной схемой, владельцем и trust metadata. |
| `locks/` | Точные проверенные версии и ревизии внешних компонентов. | Обновлять только после проверки кандидата; использовать для воспроизводимой установки и отката. |
| `schemas/` | JSON Schema всех переносимых и локальных контрактов. | Проверять новые manifest и generated state до активации. |
| `clients/` | Документация и тонкие адаптеры поддерживаемых harness. | Добавлять новый клиент через capability contract и conformance tests. |
| `src/agent_engineering_kit/` | Capability kernel, CLI, discovery, policy, run/task contracts и materialization. | Использовать публичные функции из модулей либо CLI `agent-kit`. |
| `templates/` | Начальные файлы logical project и overrides. | Создавать через команды Kit, затем уточнять только проектный слой. |
| `evals/` | Golden tasks и сравнительные проверки экспериментальных оптимизаций контекста. | Запускать до включения JEV или другого context optimizer. |
| `docs/` | ADR, согласованные дизайны, планы и канонический индекс знаний. | Начинать чтение с `docs/INDEX.md`; новые решения фиксировать отдельным ADR. |
| `tests/` | Контрактные, негативные и регрессионные проверки. | Использовать как исполняемую спецификацию CLI и форматов. |
| `bootstrap/` | Первичная установка команды и локальной структуры данных. | Запускать один раз на машине; повторный desired state поддерживает `resync`. |

## Основные принципы

- В Git находятся только универсальные и версионируемые определения.
- Долговечные знания конкретного проекта находятся в его исходном коде, тестах и документации.
- Рабочая память, локальные переопределения и сгенерированные настройки клиентов хранятся вне репозитория.
- Каждый MCP и AI-клиент самостоятельно владеет своим нативным состоянием.
- Закоммиченные определения подчиняются корпоративной политике моделей.
- Сторонние компоненты устанавливаются по точным записям lock-файлов и проверяются до активации.

## Один набор на машину

На машине используется одна каноническая рабочая копия. Codex, Codex Desktop, Claude Code, Claude Desktop, OpenCode и Cline получают из неё общие правила, действующие skills и MCP. Копировать набор внутрь рабочих проектов не нужно.

## Что находится в Git

В репозитории хранятся правила, роли агентов, собственные skills, каталоги, lock-файлы, схемы JSON, контракты безопасности, тонкие адаптеры клиентов, скрипты первоначальной установки, тесты и ADR.

## Что никогда не находится в Git

В репозиторий не попадают исходный код сторонних skills и MCP, исполняемые файлы, память проектов, базы и кэши MCP, сеансы, состояние OAuth, учётные данные, пользовательские модели, локальные переопределения, индексы и сгенерированные настройки клиентов.

## Архитектура желаемого состояния

`AI.md` служит короткой точкой входа для агента. Каталоги задают желаемое состояние, lock-файлы закрепляют проверенные ревизии, а Python CLI создаёт только локальные артефакты машины.

| Назначение | Unix по умолчанию | Windows по умолчанию |
|---|---|---|
| рабочая копия набора | `<data>/repository` | `<data>\repository` |
| установленные компоненты | `~/.local/share/agent-engineering-kit/installations` | `%LOCALAPPDATA%\agent-engineering-kit\installations` |
| состояние, блокировки и журналы | `~/.local/share/agent-engineering-kit/{state,locks,logs}` | `%LOCALAPPDATA%\agent-engineering-kit\{state,locks,logs}` |
| память проектов | `~/.local/share/agent-engineering-kit/projects` | `%LOCALAPPDATA%\agent-engineering-kit\projects` |
| локальные переопределения | `~/.local/share/agent-engineering-kit/overrides` | `%LOCALAPPDATA%\agent-engineering-kit\overrides` |

Механизм разрешения путей учитывает `XDG_DATA_HOME`, `LOCALAPPDATA`, `AGENT_KIT_DATA_HOME` и `AGENT_KIT_REPOSITORY`. Репозиторий, установки, память проектов и нативное состояние MCP намеренно разделены.

## Установка

В Unix:

```bash
./bootstrap/install.sh
agent-kit doctor
```

В PowerShell:

```powershell
.\bootstrap\install.ps1
agent-kit doctor
```

Для разработки самого набора:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Сценарий для команды, которая ведёт корпоративную копию в GitLab и периодически забирает изменения из исходного GitHub, описан в [отдельной инструкции](docs/runbooks/install-from-gitlab-fork.md).

## Первый запуск

```bash
agent-kit validate --ci
agent-kit resync --no-update
agent-kit doctor
```

`resync` устанавливает инструменты безопасности, проверяет и активирует сторонние skills, подготавливает MCP и создаёт нативные мосты для клиентов. Повторный запуск идемпотентен.

## Встроенная справка и каталог команд

`agent-kit help` показывает команды верхнего уровня. После `help` можно указать любой путь команды; вывод строится из того же CLI parser, поэтому не расходится с `--help`:

```bash
agent-kit help
agent-kit help project init
agent-kit help task lane
agent-kit help mcp docker
agent-kit help security scan
```

Обычная форма `--help` также поддерживается:

```bash
agent-kit project init --help
```

| Команда | Назначение |
|---|---|
| `agent-kit install` | Применить desired state без обновления Git checkout. |
| `agent-kit validate [target]` | Проверить схемы, каталоги, policy, Git hygiene и безопасность. |
| `agent-kit doctor` | Диагностировать установленное окружение и runtime. |
| `agent-kit sync` / `resync` | Синхронизировать локальные установки, MCP и клиентские адаптеры. |
| `agent-kit project ...` | Создать, подключить, обнаружить или сверить logical project и его память. |
| `agent-kit config explain` | Показать effective configuration, выбранный harness и происхождение решений. |
| `agent-kit skills ...` | Просмотреть, включить, отключить или переопределить skills. |
| `agent-kit mcp ...` | Просмотреть, включить, отключить или переопределить MCP. |
| `agent-kit mcp docker ...` | Управлять выделенным профилем Docker MCP Toolkit. |
| `agent-kit override ...` | Управлять локальными overrides правил, ролей, policy, tools и harness. |
| `agent-kit security ...` | Установить и запустить средства проверки skills и проекта. |
| `agent-kit pr refresh` | Обновить локальный недоверенный снимок открытого PR/MR через SCM MCP. |
| `agent-kit run ...` | Зафиксировать входной и итоговый контракт запуска внешнего harness. |
| `agent-kit task ...` | Вручную управлять workspace, lease, worktree и параллельными lanes. |
| `agent task create ...` | Начать обычную задачу: определить Jira-контекст, ветку и worktree. |

Высокоуровневая команда `agent` предназначена для ежедневной работы разработчика. Команды `agent-kit` предоставляют полный управляющий и аварийный интерфейс.

Подробная документация начинается с [канонического индекса](docs/INDEX.md). Инструкция по корпоративной схеме GitHub → GitLab находится в [отдельном runbook](docs/runbooks/install-from-gitlab-fork.md), описание MCP — в [mcp/README.md](mcp/README.md), а принятые архитектурные решения — в [docs/adr](docs/adr/).

## MCP из коробки

Каталог из коробки:

- `codebase-memory` — граф кода, архитектура, связи вызовов и анализ влияния;
- `serena` — поиск символов и ссылок, семантическое редактирование и рефакторинг;
- `context7` — актуальная документация библиотек, фреймворков и API.

Условные интеграции:

- `github` — включается при обнаружении удалённого репозитория GitHub;
- `gitlab` — включается при обнаружении удалённого репозитория GitLab;
- `sonarqube` — включается при наличии конфигурации Sonar;
- `playwright` — включается для веб-проектов;
- `atlassian` — включается при настроенных Jira или Confluence.

CBM и Serena дополняют друг друга: сначала CBM определяет область влияния, затем Serena уточняет конкретные символы и ссылки. Однако нативная регистрация выполняется только тогда, когда штатный client способен применить весь выбранный capability contract. В профиле `readonly` mixed read/write серверы (`codebase-memory`, `serena`, SCM, Playwright и Atlassian) не регистрируются целиком под видом read-only. `planned_capabilities` показывают план, а `enabled_capabilities` — только реально применённый полный surface. Локальный пользователь может выбрать более свободный профиль через override, принимая соответствующий риск.

Serena сохраняет web dashboard, но Kit запускает сервер с `--open-web-dashboard false`: страница доступна вручную и больше не открывается новой вкладкой при каждом старте MCP.

Проверить состояние:

```bash
agent-kit mcp list
agent-kit mcp status
agent-kit mcp explain <id>
```

### Docker MCP Toolkit

Docker MCP Toolkit поддерживается как опциональный способ запуска `github` и `playwright`. По умолчанию он отключён, поэтому все серверы используют прежнюю нативную регистрацию. После включения Kit управляет только выделенным профилем `agent-engineering-kit` и гарантирует для каждого MCP единственный маршрут: native либо Docker gateway.

```bash
agent-kit mcp docker status
agent-kit mcp docker plan
agent-kit mcp docker enable --scope global
agent-kit mcp docker sync
agent-kit mcp docker disable --scope global
```

`plan` ничего не изменяет. `sync` добавляет и удаляет только записи, которыми владеет Kit; пользовательские серверы в Docker profile сохраняются. Клиенты переключаются на namespaced gateway `agent-kit-docker` только после успешной сверки профиля. Если `docker mcp` недоступен, команда возвращает `CONFIG_REQUIRED`, а нативные MCP продолжают работать.

## Skills из коробки

Собственные skills:

- `greeting` — возвращает нейтральное приветствие и служит базой для примера локального override;
- `project-bootstrap` — создаёт манифест логического проекта и внешнюю память;
- `project-orientation` — определяет проект, репозитории, компоненты и документацию;
- `docs-index` — поддерживает `docs/INDEX.md`;
- `codebase-analysis` — исследует структуру и потоки данных;
- `change-impact` — оценивает входящее и исходящее влияние изменения;
- `code-review` — проверяет изменения на дефекты и регрессии;
- `verification` — подтверждает критерии приёмки воспроизводимыми проверками;
- `mcp-doctor` — диагностирует регистрацию и состояние MCP.

Внешний набор Superpowers устанавливается отдельно и предоставляет:

- `using-superpowers`;
- `brainstorming`;
- `writing-plans`;
- `executing-plans`;
- `dispatching-parallel-agents`;
- `subagent-driven-development`;
- `using-git-worktrees`;
- `test-driven-development`;
- `systematic-debugging`;
- `verification-before-completion`;
- `requesting-code-review`;
- `receiving-code-review`;
- `finishing-a-development-branch`;
- `writing-skills`.

Проверить состояние:

```bash
agent-kit skills list
agent-kit skills status
agent-kit skills explain <id>
```

## Как работать с проектом

### 1. При необходимости подключить logical project

Выполни команду из каталога будущего проекта:

```bash
agent-kit project init
# Если менять repository нельзя:
agent-kit project attach /workspace/my-project --id my-project
```

В интерактивном терминале `project init` предлагает язык и стек из версионируемого `catalog/project-templates.yaml`, основную ветку и при необходимости выполняет `git init`. Существующие файлы не перезаписываются. Для CI те же настройки задаются явно:

```bash
agent-kit project init ./orders \
  --template python-fastapi \
  --git \
  --default-branch main
```

Project manifest необязателен для общих настроек Kit. `project init` создаёт версионируемый `.ai-team/project.yaml`; `project attach` создаёт descriptor только в локальных данных машины и не меняет исходный repository. Компоненты Maven, Gradle, Node.js, Go, Cargo, .NET, Python и Bazel обнаруживаются автоматически. Поле `components` нужно только для ownership, criticality и дополнительных логических границ. Настройку Jira можно объявить в `integrations.jira` через `project_key`, `cloud_id` и `site_url`.

При `project init` Kit сразу строит полный граф Codebase Memory и индекс символов Serena для каждого доступного репозитория logical project. Перед управляемыми запусками агентов (`run prepare`, высокоуровневый `task create`, создание lane) индексы обновляются в быстром режиме. После изменений, выполненных внешним harness в обход этих точек, запусти обновление явно:

```bash
agent-kit project memory-refresh
```

Сводка сохраняется в `<data>/projects/<project-id>/integrations/memory-index.json`. Нативные индексы MCP не добавляются в Git. Индексы также обновляются после `task complete` и `lane complete`, когда интегрированные изменения уже находятся в общей ветке задачи.

Проверь результат:

```bash
agent-kit project status .
agent-kit project reconcile .
agent-kit project reconcile . --apply
agent-kit config explain .
```

### 2. Начать рабочий сеанс

```bash
agent-kit resync
agent-kit doctor
```

После этого открой `docs/INDEX.md`, выбери нужную роль агента и используй только MCP и skills, относящиеся к задаче. Ревизию набора не следует менять до окончания текущей задачи.

### 3. Создать задачу и рабочее дерево

```bash
# Jira URL и обычный ID поддерживаются одинаково.
agent task create https://company.atlassian.net/browse/TASK-123
agent task create SOME-ID --type fix
```

Если Jira настроена и доступна, Kit добавляет summary и выбирает тип ветки по типу задачи. Если issue не найден, ID всё равно используется, а summary в имени ветки отсутствует. `--type` всегда имеет приоритет. Формат ветки: `<type>/dd-MM-yyyy-<task-id>-<summary>`. При занятом имени создаётся `-copy-N` от исходного base commit.

Низкоуровневый fallback не требует Jira и сам определяет project по текущему каталогу:

```bash
agent-kit task create TASK-123 \
  --type feat \
  --summary orders \
  --write 'services/orders/**'
agent-kit task status TASK-123
agent-kit task retry TASK-123
```

Локальная бронь области записи, или lease, предотвращает пересекающиеся изменения только на одной машине. При конфликте более поздняя задача получает `WAITING`; `status` показывает блокирующую задачу и пути. Между компьютерами синхронизацию обеспечивают Git remote, PR/MR, CI и merge queue.

Для параллельных агентов внутри одной задачи используются отдельные lane-ветки и worktree:

```bash
agent task lane create TASK-123 api --write 'services/orders/api/**'
agent task lane create TASK-123 tests --write 'services/orders/tests/**'
agent task lane status TASK-123
agent task lane integrate TASK-123 api
# Выполни напечатанный git merge обычной Git-командой.
agent task lane complete TASK-123 api
```

Непересекающиеся lanes работают параллельно. Изменения общих файлов обслуживаются по очереди. `lane integrate` только проверяет состояние и печатает Git-команды; commit и merge Kit не выполняет.

Для воспроизводимого запуска harness отдельно подготовь manifest:

```bash
agent-kit run prepare . --profile developer --verify pytest
```

`run prepare` сохраняет request manifest с ревизиями, effective policy, conventions, ролями, skills, MCP и разрешениями.

### 4. Выполнить изменение

1. Создай ветку `<type>/dd-MM-yyyy-<description>`.
2. Определи затронутые репозитории и компоненты через `.ai-team/project.yaml`.
3. Оцени влияние изменения, затем внеси минимальный связный набор правок.
4. Добавь или обнови тесты.
5. Если изменился контракт или архитектура, обнови документацию проекта.

Перед записью агент обязан выполнить `agent task lane status <task-id> <lane-id>`. Статус `WAITING` запрещает изменение файлов. После расширения write set проверка выполняется повторно.

### Обновить контекст текущего PR/MR

```bash
# Найти единственный открытый PR/MR текущей ветки.
agent-kit pr refresh

# Либо указать номер или URL.
agent-kit pr refresh 152
agent-kit pr refresh https://github.com/acme/orders/pull/42

agent-kit pr status
agent-kit pr show
```

URL определяет провайдера первым, затем используется Git remote, а GitLab является значением по умолчанию. GitLab вызывается через `list_merge_requests` и `get_merge_request`; GitHub — через `list_pull_requests` и `pull_request_read`. GitHub запускается в read-only и lockdown режимах. Снимок сохраняется только в machine-local памяти проекта, ограничивается по размеру и считается недоверенными данными. Команда ничего не изменяет в PR/MR.

Официальная документация: [GitLab MCP server](https://docs.gitlab.com/user/model_context_protocol/mcp_server/), [GitHub MCP server](https://github.com/github/github-mcp-server).

### 5. Проверить и зафиксировать результат

```bash
pytest
agent-kit validate
agent-kit validate --ci
agent-kit doctor
agent-kit run record-result <run-id> --project-id my-project --status passed \
  --verification-json '[{"id":"pytest","status":"passed"}]'
```

Перед коммитом убедись, что в подготовленных изменениях нет секретов, локальных моделей, переопределений или сгенерированного состояния среды выполнения.

### 6. Завершить работу

После интеграции коммитов явно заверши task workspace. Lease освобождается только после этого, а локальное состояние удаляется только при отсутствии активного lease и существующих managed worktree:

```bash
agent-kit task complete my-project TASK-123
agent-kit task release my-project TASK-123
# Сначала безопасно удали созданные Git worktree штатной командой git worktree remove.
agent-kit task gc my-project TASK-123
```

`task gc` откажется удалять каталог с неизвестными файлами. Если задача ещё выполняется, имеет активный lease или её managed worktree существует, очистка также будет заблокирована.

Используй коммит формата `<type>(<scope>): <description>`, обнови `app.version` и создай Pull Request. Прямая отправка изменений в `main` запрещена.

## Параллельный вайбкодинг несколькими разработчиками

Локальные leases защищают только одну машину. Между разными ПК источником координации остаётся Git: отдельные remote branches, Pull Request, CI и merge queue. Kit делает конфликт видимым раньше, но не создаёт распределённую блокировку без общего сервиса.

Рекомендуемый процесс:

1. Каждый разработчик обновляет базовую ветку и создаёт собственную ветку по соглашению `<type>/dd-MM-yyyy-<description>`.
2. Для задачи фиксируется `task workspace`: project ID, task ID, revision vector репозиториев и write set. Эти данные можно приложить к задаче или PR, не включая локальные абсолютные пути.
3. На каждом ПК используется отдельный worktree. Один writable lane владеет одним worktree; два агента не редактируют один checkout одновременно.
4. Пересекающиеся write sets требуют сериализации или явного разделения файлов. Непересекающиеся сервисы и модули можно вести параллельно.
5. Изменения передаются только коммитами и remote branch. Worktree между компьютерами не синхронизируются и не копируются.
6. Перед merge разработчик обновляет ветку от актуального `main`, повторно запускает discovery, тесты и `agent-kit validate --ci`. Merge queue последовательно применяет прошедшие CI изменения.
7. Горячие документы (`README.md`, `docs/INDEX.md`, общие ADR-списки) имеют одного integration owner. Остальные участники создают уникальные change fragments или отдельные ADR; integrator выполняет одну детерминированную сборку.

Если нужного репозитория на ПК нет, `project status` возвращает `BLOCKED` для обязательного и `DEGRADED` для необязательного binding. Агент не должен молча исключать обязательный репозиторий из impact analysis. После клонирования используется `project bind`, затем `project reconcile`.

## Адаптеры клиентов

### Codex и Codex Desktop

Используются `~/.codex/AGENTS.md`, `~/.agents/skills` и `~/.codex/config.toml`. Набор изменяет только собственные записи MCP с префиксом пространства имён и управляемый блок инструкций.

### Claude Code

Используются `~/.claude/CLAUDE.md`, `~/.claude/skills` и пользовательская конфигурация MCP. Конечные точки OAuth могут потребовать интерактивного подтверждения.

### Claude Desktop

Для Desktop действует отдельный контракт интеграции. MCP и Desktop Extensions настраиваются нативно; возможности глобальных инструкций файловой системы ограничены самим клиентом.

### OpenCode

Используются `AGENTS.md`, нативный поиск Agent Skills и собственная MCP-конфигурация OpenCode.

### Cline

Используются `AGENTS.md`, Cline Rules и нативные настройки MCP. Набор не перезаписывает недокументированные пользовательские пути.

## Правила и роли агентов

Каталог `rules/` содержит обязательные правила разработки, Git, тестирования, проверки, документации, безопасности, контекста, моделей и внешних инструментов. Конфигурация проекта может их уточнять, но не ослаблять обязательные ограничения.

Каталог `agents/` содержит пять подробно описанных ролей:

- `orchestrator` — принимает задачу, выбирает процесс, координирует этапы и отвечает за итоговый handoff;
- `architect` — определяет границы, интерфейсы, влияние, миграцию и архитектурные компромиссы;
- `developer` — реализует согласованное изменение через test-first цикл и готовит проверяемый diff;
- `reviewer` — независимо проверяет корректность, безопасность, совместимость и достаточность тестов;
- `qa-engineer` — воспроизводимо подтверждает критерии приёмки и фиксирует ограничения среды.

Переносимые определения ролей и их содержимое по умолчанию написаны на английском, чтобы одинаково интерпретироваться разными клиентами и моделями. Пользовательская документация и эксплуатационные инструкции Kit остаются на русском.

## Сторонние skills

`catalog/skills.yaml` и `locks/skills.lock.yaml` управляют сторонними skills без копирования их исходного кода. Superpowers закреплён на проверенной ревизии и устанавливается только в `<data>/installations/skills/`. До состояния `ACTIVE` кандидат проходит проверку источника, сканирование безопасности, политику моделей и проверку совместимости с клиентами.

## Безопасность

Секреты хранятся только в переменных окружения или внешнем хранилище секретов; их имена перечислены в `.env.example`. Набор инструментов безопасности включает SkillEvaluator, SkillSpector, Semgrep, Gitleaks и Bumblebee. В CI используется закреплённая версия Gitleaks.

```bash
agent-kit security status
agent-kit security doctor
agent-kit security scan
agent-kit security validate
```

`agent-kit install` и `agent-kit resync` устанавливают закреплённые версии Bumblebee и SkillSpector вместе с остальными обязательными средствами безопасности. `security scan [path]` запускает Bumblebee для инвентаризации dependency/tool metadata проекта и SkillSpector для всех действующих skills. SkillSpector работает с `--no-llm`, поэтому проверка не отправляет содержимое skills внешней модели. Сводный отчёт хранится в `<data>/state/reports/security/`.

## Политика моделей

Отслеживаемый файл `models/corporate.yaml` задаёт разрешённых провайдеров, идентификаторы, псевдонимы и способности моделей. При непустом списке только эти модели могут использоваться в закоммиченных определениях.

Пользовательские модели задаются вне рабочей копии в `<data>/overrides/models.yaml`; защитный путь `models/user.local.yaml` исключён из Git. Локальные модели расширяют только рабочее окружение конкретной машины.

## Локальные переопределения

Переопределения находятся вне репозитория:

```text
<data>/overrides/global/{rules,skills,agents,mcp,policy}/
<data>/overrides/projects/<project-id>/{rules,skills,agents,mcp,policy}/
```

Приоритет: исходный поставщик < набор < закоммиченная конфигурация проекта < глобальная конфигурация пользователя < конфигурация пользователя для проекта. Для компонентных overrides поддерживаются режимы `extend`, `replace` и `disable`; параметры policy задаются целиком через `replace`. Владелец машины может локально изменить или отключить любой skill и MCP, включая базовые элементы `required`, `locked` и `enforced`. Эти изменения не модифицируют корпоративную основу в Git: `agent-kit validate --ci` проверяет её без локальных входов.

Общий интерфейс охватывает роли, rules, модели, skills, MCP, approvals, sandbox, сеть, tools и harness:

```bash
agent-kit override list --scope global
agent-kit override set approvals profile --mode replace \
  --from approval.local.yaml --reason 'Изолированная локальная среда' --scope global
agent-kit override explain approvals profile --scope global
agent-kit override reset approvals profile --scope global
```

Чтобы осознанно разрешить полный смешанный MCP surface на локальной машине, выбери более свободный профиль; причина попадёт в provenance:

```bash
printf 'value: administrator\n' > mcp-profile.local.yaml
agent-kit override set mcp access-profile --mode replace \
  --from mcp-profile.local.yaml --reason 'Локальная изолированная среда' --scope global
agent-kit mcp available
```

Локальный YAML не добавляется в Git. Бюджет инструментов и конфликты capabilities продолжают действовать; ненужные MCP можно отключить отдельным override, чтобы освободить бюджет для нужного сервера.

## Логические проекты и память

`.ai-team/project.yaml` задаёт стабильный ID, репозитории, компоненты, документацию и пространство имён памяти. Git-репозиторий является частью топологии, но не идентичностью проекта.

Раздел `harness` задаёт предпочтительный клиент и обязательные управляемые возможности. Значение `preferred_client: auto` сохраняет свободу пользователя и выбирает первый совместимый адаптер; явный ID клиента проверяется до запуска синхронизации.

Локальная память находится в `<data>/projects/<project-id>/`. Авторитетные знания остаются в исходном коде, тестах и `docs/`; данные MCP и клиентов остаются в их нативных хранилищах.

## Монорепозитории и рабочие пространства из нескольких репозиториев

В монорепозитории один репозиторий может содержать несколько компонентов. В рабочем пространстве из нескольких репозиториев манифест перечисляет соседние репозитории относительно общего логического корня. Анализ влияния выполняется по всем компонентам, а Git-команды — отдельно в каждом репозитории.

## Индекс документации

`docs/INDEX.md` — каноническая карта долговечных знаний: архитектуры, ADR и эксплуатационных инструкций. Первоначальная настройка создаёт минимальный файл, но не перезаписывает существующий текст.

## Обновление и откат

Обновление самого набора (`git fetch` и `git pull --ff-only`) отделено от обновления внешних зависимостей. Новая версия внешнего компонента сначала проходит проверку, затем получает новую запись в lock-файле и только после этого активируется.

```bash
agent-kit skills rollback <id>
```

Для MCP и инструментов безопасности откат выполняется возвратом lock-файла и повторным `resync`.

## JEV и оптимизация контекста

JEV описан как экспериментальная capability и по умолчанию выключен. Включение разрешено только локальным opt-in после сравнительного прогона golden tasks из `evals/`: качество не должно ухудшаться, экономия токенов измеряется отдельно, а ошибка оптимизатора обязана приводить к безопасному fail-through без потери исходного контекста. Kit не делает JEV обязательным для клиента и не предполагает, что каждый harness поддерживает его нативно.

## Диагностика

- Если логический проект не найден, выполни `agent-kit project init` в его общем корне.
- При конфликте `project.id` выбери новый стабильный ID; не удаляй чужую память вручную.
- Если рабочая копия набора содержит незакоммиченные изменения, сначала зафиксируй или временно отложи их: автоматический сброс не выполняется.
- Если MCP недоступен, проверь команду, конечную точку и наличие требуемой переменной окружения, не выводя её значение.
- Чтобы увидеть происхождение действующей настройки, выполни `agent-kit config explain`.
- Если локальная проверка отличается от CI, повтори `agent-kit validate --ci`: этот режим намеренно не читает пользовательские переопределения.
