# План реализации harness control plane

Этот рабочий план связывает архитектурное решение с конкретными изменениями исходного кода, схем, тестов и документации. Каждый этап должен оставлять репозиторий в проверяемом состоянии, а итоговые формулировки обязаны быть понятны разработчику без чтения внутренней реализации.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Цель:** Закрепить Agent Engineering Kit как проверяемый control plane для внешних agent harness и восстановить подробный базовый набор ролей.

**Архитектура:** Новый модуль `harness.py` читает декларативный каталог клиентов, выбирает совместимый адаптер и формирует воспроизводимый контракт. Существующие `resync`, `config explain` и project manifest используют этот модуль, не принимая на себя execution loop клиента.

**Стек:** Python 3.10+, pytest, YAML, JSON Schema, Markdown.

**Спецификация:** `docs/superpowers/specs/2026-10-09-harness-control-plane-design.md`

## Общие ограничения

- Базовые описания ролей, first-party skills, MCP и client harness пишутся на английском.
- Пользовательская документация, комментарии YAML и сообщения CLI пишутся на русском.
- Пользователь может локально отключить или заменить любой skill и MCP.
- Kit остаётся control plane; execution loop, sandbox и approvals принадлежат клиенту.
- Старые project manifests без раздела `harness` остаются валидными.

---

### Задача 1: языковая политика и обязательные роли

**Файлы:**
- Create: `agents/orchestrator.md`
- Create: `agents/architect.md`
- Create: `agents/developer.md`
- Create: `agents/reviewer.md`
- Create: `agents/qa-engineer.md`
- Modify: `src/agent_engineering_kit/definitions.py`
- Modify: `skills/first-party/*/SKILL.md`
- Modify: `rules/documentation.md`
- Test: `tests/test_repository.py`

**Интерфейсы:**
- Принимает: Markdown frontmatter через `markdown_frontmatter(path)`.
- Возвращает: обязательный набор ID и проверку английских переносимых описаний.

- [ ] **Шаг 1: добавить падающие тесты обязательных ролей и английских описаний**
- [ ] **Шаг 2: запустить целевые тесты и подтвердить ожидаемое падение**
- [ ] **Шаг 3: создать подробные роли и перевести описания skills**
- [ ] **Шаг 4: реализовать минимальную проверку языка и состава ролей**
- [ ] **Шаг 5: запустить целевые тесты до успешного результата**

### Задача 2: описания MCP и полная свобода overrides

**Файлы:**
- Modify: `mcp/registry.yaml`
- Modify: `schemas/mcp.schema.json`
- Modify: `src/agent_engineering_kit/definitions.py`
- Modify: `src/agent_engineering_kit/overrides.py`
- Modify: `src/agent_engineering_kit/mcp_manager.py`
- Modify: `src/agent_engineering_kit/external_skills.py`
- Test: `tests/test_overrides.py`
- Test: `tests/test_repository.py`

**Интерфейсы:**
- Принимает: `description` каждого MCP и локальные режимы `extend|replace|disable`.
- Возвращает: валидный английский каталог и итоговую конфигурацию без запрета по `required|locked|enforced`.

- [ ] **Шаг 1: добавить падающие тесты английских MCP descriptions и полного replace**
- [ ] **Шаг 2: подтвердить ожидаемое падение**
- [ ] **Шаг 3: расширить схему и реестр MCP**
- [ ] **Шаг 4: удалить запрет ослабления локального базового профиля**
- [ ] **Шаг 5: запустить тесты overrides и schemas**

### Задача 3: capability contract клиентских harness

**Файлы:**
- Create: `src/agent_engineering_kit/harness.py`
- Modify: `catalog/clients.yaml`
- Modify: `schemas/clients.schema.json`
- Modify: `schemas/project.schema.json`
- Modify: `templates/project/project.yaml`
- Modify: `src/agent_engineering_kit/projects.py`
- Modify: `src/agent_engineering_kit/clients.py`
- Test: `tests/test_harness.py`
- Test: `tests/test_projects.py`
- Test: `tests/test_clients.py`

**Интерфейсы:**
- Возвращает: `resolve_harness(repository, project) -> dict[str, object]`.
- Contract keys: `control_plane`, `execution_owner`, `preferred_client`, `selected_client`, `required_capabilities`, `managed_capabilities`, `delegated_capabilities`.

- [ ] **Шаг 1: написать тесты выбора `auto`, явного клиента и несовместимых требований**
- [ ] **Шаг 2: подтвердить ожидаемое падение**
- [ ] **Шаг 3: реализовать декларативный resolver**
- [ ] **Шаг 4: добавить harness в шаблон и инициализацию проекта**
- [ ] **Шаг 5: проверить schemas и project validation**

### Задача 4: объяснение и воспроизводимый manifest сеанса

**Файлы:**
- Modify: `src/agent_engineering_kit/explain.py`
- Modify: `src/agent_engineering_kit/resync.py`
- Test: `tests/test_clients.py`
- Test: `tests/test_resync.py`

**Интерфейсы:**
- Принимает: `resolve_harness` и `effective-policy.json`.
- Возвращает: человекочитаемый раздел `Harness` и поля `harness`, `effective_policy_sha256` в `effective-environment.json`.

- [ ] **Шаг 1: добавить падающие тесты explain и session manifest**
- [ ] **Шаг 2: подтвердить ожидаемое падение**
- [ ] **Шаг 3: добавить harness resolution и SHA-256 policy**
- [ ] **Шаг 4: запустить целевые тесты**

### Задача 5: документация, версия и полная проверка

**Файлы:**
- Modify: `README.md`
- Modify: `AI.md`
- Modify: `docs/INDEX.md`
- Modify: `docs/adr/0007-local-overrides.md`
- Create: `docs/adr/0012-harness-control-plane.md`
- Modify: `app.version`
- Modify: `src/agent_engineering_kit/__init__.py`

**Интерфейсы:**
- Возвращает: единое описание архитектуры, языка и локальной свободы пользователя.

- [ ] **Шаг 1: обновить русскоязычную документацию и ADR**
- [ ] **Шаг 2: поднять minor-версию до `0.4.0`**
- [ ] **Шаг 3: запустить `pytest`**
- [ ] **Шаг 4: запустить `agent-kit validate --ci` и `agent-kit validate`**
- [ ] **Шаг 5: проверить Git diff, отсутствие секретов и незапланированных файлов**
