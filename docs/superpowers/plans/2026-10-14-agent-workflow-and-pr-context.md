# План реализации автоматического workflow задач и контекста PR/MR

> **Для агентных исполнителей:** обязательно применять `superpowers:executing-plans` и выполнять этапы через тесты. Делегирование не требуется: изменения затрагивают общий CLI и выполняются последовательно.

**Цель:** добавить интерактивную инициализацию проекта, автоматическое создание task worktree, загрузку контекста PR/MR через MCP и отключение автоматического открытия Serena dashboard.

**Архитектура:** `agent` является тонким высокоуровневым интерфейсом над доменными сервисами Kit, а `agent-kit` сохраняет явный fallback и диагностику. MCP-вызовы изолируются адаптером, снимки PR/MR сохраняются в machine-local project memory, а Git-мутации ограничиваются `git init`, созданием ветки и worktree.

**Стек:** Python 3.10+, argparse, PyYAML, официальный MCP Python SDK совместимой ветки, pytest, Git CLI.

**Спецификация:** `docs/superpowers/specs/2026-10-14-agent-workflow-and-pr-context-design.md`

## Общие ограничения

- Не выполнять commit, push, создание, merge или изменение PR/MR.
- Не сохранять OAuth-токены, PR/MR-снимки и Jira-данные в Git-репозитории.
- Не перезаписывать существующие файлы при `project init`.
- GitLab является провайдером по умолчанию, но URL и remote имеют больший приоритет.
- Все новые YAML-файлы и новые логические блоки YAML снабжаются русскими комментариями.
- Пользовательские `.ai/` и `uv.lock` не изменяются и не добавляются в commit.

---

### Этап 1. Каталог шаблонов и интерактивный `project init`

**Файлы:**

- Создать: `catalog/project-templates.yaml`
- Создать: `src/agent_engineering_kit/project_templates.py`
- Изменить: `src/agent_engineering_kit/projects.py`
- Изменить: `src/agent_engineering_kit/cli.py`
- Тестировать: `tests/test_project_templates.py`, `tests/test_cli.py`

**Контракт:** `load_project_templates(repository) -> list[dict]`; `select_project_template(...) -> dict`; `init_project(..., template_id, initialize_git, default_branch) -> LogicalProject`.

- [ ] Написать тест, который ожидает загрузку шаблонов, отказ при неизвестном ID и создание файлов без перезаписи конфликтов.
- [ ] Запустить целевые тесты и подтвердить падение из-за отсутствующего модуля.
- [ ] Реализовать каталог, интерактивный выбор только при TTY и эквивалентные параметры `--template`, `--language`, `--stack`, `--git`, `--default-branch`.
- [ ] Реализовать `git init -b <branch>` только при отсутствии `.git`.
- [ ] Запустить целевые тесты до успешного результата.

### Этап 2. Имена веток и автоматический task workflow

**Файлы:**

- Создать: `src/agent_engineering_kit/task_workflow.py`
- Создать: `src/agent_engineering_kit/agent_cli.py`
- Изменить: `src/agent_engineering_kit/tasks.py`
- Изменить: `src/agent_engineering_kit/worktrees.py`
- Изменить: `src/agent_engineering_kit/cli.py`
- Изменить: `pyproject.toml`
- Тестировать: `tests/test_task_workflow.py`, `tests/test_cli.py`, `tests/test_worktrees.py`

**Контракт:** `build_branch_name(task_id, summary, branch_type, date) -> str`; `create_or_resume_task(...) -> TaskWorkflowResult`; `create_lane(...) -> LaneResult`; entry point `agent = agent_engineering_kit.agent_cli:main`.

- [ ] Написать тесты для имени с summary, имени без summary, `--type` и суффикса `-copy-N`.
- [ ] Подтвердить ожидаемое падение тестов.
- [ ] Реализовать единый workflow создания snapshot, автоматической локальной брони, ветки и worktree.
- [ ] Сделать повтор команды идемпотентным: завершённые этапы не повторяются, незавершённые продолжает `retry`.
- [ ] Добавить очередь write set: пересекающаяся задача получает `WAITING`, а `task status` объясняет блокирующую задачу и пути.
- [ ] Перед каждым agent run повторно проверять бронь; изменение write set требует повторного решения.
- [ ] Добавить `agent task lane create`, `lane status` и интеграционную проверку без выполнения commit или merge.
- [ ] Разрешать параллельную работу только непересекающимся lanes; общие файлы обслуживать последовательно.
- [ ] Добавить `task status` и скрыть отдельную команду lease из обычной документации, сохранив совместимость старого CLI.
- [ ] Запустить целевые тесты до успешного результата.

### Этап 3. Jira enrichment без обязательной зависимости от Jira

**Файлы:**

- Создать: `src/agent_engineering_kit/issue_context.py`
- Изменить: `src/agent_engineering_kit/task_workflow.py`
- Тестировать: `tests/test_issue_context.py`, `tests/test_task_workflow.py`

**Контракт:** `resolve_issue(reference, project, mcp_client) -> IssueContext`; отсутствие результата возвращает нормализованный task ID и `summary=None`, а не блокирует workflow.

- [ ] Написать тесты Jira URL, простого ID, отсутствующего issue и приоритета `--type`.
- [ ] Подтвердить ожидаемое падение тестов.
- [ ] Реализовать read-only вызов Jira MCP и fallback без summary.
- [ ] Запустить целевые тесты до успешного результата.

### Этап 4. MCP-клиент и обновление PR/MR

**Файлы:**

- Создать: `src/agent_engineering_kit/mcp_client.py`
- Создать: `src/agent_engineering_kit/pull_requests.py`
- Изменить: `src/agent_engineering_kit/cli.py`
- Изменить: `mcp/registry.yaml`
- Изменить: `catalog/corporate/mcp.yaml`
- Тестировать: `tests/test_mcp_client.py`, `tests/test_pull_requests.py`, `tests/test_cli.py`

**Контракт:** `PullRequestService.refresh(reference, project, repository_id) -> Path`; `McpToolClient.call(server_id, tool, arguments) -> dict`.

- [ ] Написать тесты определения GitLab/GitHub по URL и remote, поиска единственного open PR/MR текущей ветки и ошибок при нуле/нескольких результатах.
- [ ] Написать тест атомарного локального снимка с provenance, лимитами и без секретов.
- [ ] Подтвердить ожидаемое падение тестов.
- [ ] Реализовать GitLab `list_merge_requests`/`get_merge_request` и GitHub `pull_request_read` через узкий MCP-адаптер.
- [ ] Ограничить dedicated reader GitHub/GitLab наборами `pull_requests` и `merge_requests`; не заявлять отсутствующую серверную read-only гарантию GitLab.
- [ ] Реализовать `agent-kit pr refresh`, `pr show` и `pr status`.
- [ ] Запустить целевые тесты до успешного результата.

### Этап 5. Serena без автоматических вкладок

**Файлы:**

- Изменить: `mcp/registry.yaml`
- Тестировать: `tests/test_mcp_manager.py`, `tests/test_clients.py`

- [ ] Написать тест регистрации Serena с `--open-web-dashboard false` и идемпотентного повторного resync.
- [ ] Подтвердить падение теста на текущем registry.
- [ ] Добавить аргументы с русским комментарием.
- [ ] Запустить целевые тесты до успешного результата.

### Этап 6. Документация, версия и полная проверка

**Файлы:**

- Изменить: `README.md`
- Изменить: `AI.md`
- Изменить: `docs/INDEX.md`
- Изменить: `.env.example`
- Изменить: `app.version`

- [ ] Описать различие `agent` и `agent-kit`, local lease, project templates, Jira fallback и PR/MR refresh на понятном русском языке.
- [ ] Перечислить новые переменные окружения без секретных значений.
- [ ] Повысить minor-версию в `app.version`.
- [ ] Запустить `.venv/bin/python -m pytest -q`.
- [ ] Запустить `.venv/bin/agent-kit validate --ci` либо эквивалент через `python -m`.
- [ ] Проверить `git diff --check` и убедиться, что `.ai/` и `uv.lock` не включены в изменения.
