# План реализации capability kernel

> План реализуется последовательно через red-green-refactor. Каждый этап должен оставлять CLI и существующие manifest версии 1 работоспособными.

## Этап 1. Conventions и capability policy

**Файлы:**

- создать `conventions/*.yaml`;
- создать `schemas/conventions.schema.json`, `schemas/policy-override.schema.json`;
- создать `src/agent_engineering_kit/conventions.py`, `src/agent_engineering_kit/policy.py`;
- изменить `src/agent_engineering_kit/validation.py`, `src/agent_engineering_kit/explain.py`;
- добавить `tests/test_conventions.py`, `tests/test_policy.py`.

1. Написать отрицательные тесты schema validation, path escape и попытки переопределить invariant.
2. Реализовать загрузку общих и project conventions с additive merge.
3. Реализовать классификацию `preference`, `restriction`, `invariant` и provenance каждого решения.
4. Проверить, что local override обходит restriction с предупреждением, но invariant блокирует активацию.
5. Добавить JSON-вывод effective policy и provenance.

## Этап 2. Logical project, bindings и component discovery

**Файлы:**

- создать `src/agent_engineering_kit/discovery.py`, `src/agent_engineering_kit/bindings.py`;
- создать `schemas/project-bindings.schema.json`, `schemas/component-inventory.schema.json`;
- изменить `schemas/project.schema.json`, `templates/project/project.yaml`;
- изменить `src/agent_engineering_kit/projects.py`, `src/agent_engineering_kit/cli.py`;
- добавить `tests/test_discovery.py`, расширить `tests/test_projects.py`, `tests/test_cli.py`.

1. Написать тесты обнаружения Maven, Gradle, Node workspace, Go, Cargo, .NET и Python компонентов.
2. Реализовать стабильные component IDs, тип, evidence, confidence и зависимости там, где формат позволяет.
3. Сохранять inventory в project state, но не добавлять его в Git.
4. Добавить local project descriptor и repository bindings без абсолютных путей в committed manifest.
5. Реализовать состояния `READY`, `DEGRADED`, `BLOCKED`, `MISMATCHED`.
6. Добавить `project attach`, `project bind`, `project reconcile` и безопасный preview structural diff.

## Этап 3. Унифицированные overrides и permission profiles

**Файлы:**

- изменить `src/agent_engineering_kit/overrides.py`, `src/agent_engineering_kit/override_service.py`, `src/agent_engineering_kit/cli.py`;
- создать `profiles/developer.yaml`, `profiles/tester.yaml`, `profiles/reviewer.yaml`;
- создать `schemas/profile.schema.json`;
- расширить `tests/test_overrides.py`, `tests/test_override_service.py`, `tests/test_cli.py`.

1. Добавить обязательный `reason` для новых policy overrides.
2. Поддержать виды `agents`, `rules`, `models`, `skills`, `mcp`, `approvals`, `sandbox`, `network`, `tools`, `harness`.
3. Добавить команды `override list/explain/set/reset`.
4. Сохранить команды skills/MCP как совместимые фасады.
5. Добавить независимые permission profiles `readonly`, `autonomous`, `custom` и их компиляцию в capability contract клиента.

## Этап 4. Run contracts и события

**Файлы:**

- создать `src/agent_engineering_kit/runs.py`, `src/agent_engineering_kit/events.py`;
- создать `schemas/run-manifest.schema.json`, `schemas/run-event.schema.json`;
- изменить `src/agent_engineering_kit/resync.py`, `src/agent_engineering_kit/cli.py`;
- добавить `tests/test_runs.py`, `tests/test_events.py`.

1. Написать тесты детерминированного manifest и удаления секретных значений.
2. Реализовать request/result manifests с разделением планируемого и фактического состояния.
3. Реализовать append-only JSONL события со schema validation и redaction.
4. Добавить команды `run prepare`, `run record-result`, `run events`.
5. Сохранять policy, conventions и repository revision digests.

## Этап 5. Корпоративные MCP и защита данных

**Файлы:**

- создать `catalog/corporate/mcp.yaml`, `catalog/corporate/data-classification.yaml`, `catalog/corporate/access-profiles.yaml`;
- расширить `schemas/mcp.schema.json`;
- изменить `src/agent_engineering_kit/mcp_manager.py`, `src/agent_engineering_kit/definitions.py`;
- создать `rules/corporate-data.md`, `rules/untrusted-content.md`, `rules/mcp-access.md`, `rules/data-analysis.md`;
- расширить `tests/test_mcp_manager.py`, `tests/test_repository.py`.

1. Добавить trust, owner, capabilities, data classes, auth, boundaries и audit metadata.
2. Реализовать capability conflicts и tool budget.
3. Разделить read/write/admin возможности и выключить write/admin по умолчанию.
4. Проверить отсутствие literal secrets и credentials в remote/endpoint URL.
5. Материализовать правила защиты от prompt injection, минимизации данных, redaction и task-scoped доступа.

## Этап 6. Task workspace и безопасная работа с worktree

**Файлы:**

- создать `src/agent_engineering_kit/tasks.py`, `src/agent_engineering_kit/worktrees.py`;
- создать `schemas/task-workspace.schema.json`;
- изменить `src/agent_engineering_kit/cli.py`;
- добавить `tests/test_tasks.py`, `tests/test_worktrees.py`.

1. Написать тесты write-set overlap, leases и repository revision vector.
2. Реализовать task workspace отдельно от `resync`.
3. Добавить dry-run план worktree и безопасное создание только для явных repository bindings.
4. Запретить совместное владение writable worktree и изменение primary checkout.
5. Реализовать release/GC только для завершённых task workspace без активных leases.

## Этап 7. Документационный workflow, conformance и evals

**Файлы:**

- создать `src/agent_engineering_kit/documentation.py`, `src/agent_engineering_kit/conformance.py`;
- создать `evals/golden-tasks.yaml`, `evals/context-optimization.yaml`;
- изменить `catalog/clients.yaml`, `schemas/clients.schema.json`;
- обновить `README.md`, `AI.md`, `docs/INDEX.md`, ADR и client README;
- добавить `tests/test_documentation.py`, `tests/test_conformance.py`.

1. Проверить ownership, уникальные change fragments и ADR IDs.
2. Добавить детерминированную генерацию docs index без конкурентного ручного редактирования.
3. Добавить client conformance matrix и проверку capabilities.
4. Описать JEV как выключенную experimental capability с обязательным comparative eval.
5. Добавить lifecycle/GC runbook и карту всех новых каталогов.

## Итоговая проверка

1. Запустить целевые тесты после каждого этапа.
2. Запустить `pytest` полностью.
3. Запустить `agent-kit validate --ci`.
4. Запустить `agent-kit resync --no-update` и проверить idempotency.
5. Выполнить `git diff --check`, secret scan и обзор итогового diff.
6. Обновить `app.version` до новой minor-версии.
