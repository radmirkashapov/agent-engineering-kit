# План реализации базовых SDLC-ролей агентов

> **Для agentic workers:** ОБЯЗАТЕЛЬНЫЙ SUB-SKILL: используйте `superpowers:subagent-driven-development` (рекомендуется) или `superpowers:executing-plans`, чтобы выполнять план по задачам. Для отслеживания шагов используются checkbox (`- [ ]`).

**Цель:** расширить поставляемый Kit набор с пяти до девяти подробных англоязычных SDLC-ролей, не меняя profiles, skills и семантику `project init`.

**Архитектура:** новые роли остаются декларативными Markdown-manifests в `agents/` и проходят существующую JSON Schema/English-проверку. `DEFAULT_AGENT_IDS` задаёт точный обязательный набор, а русскоязычные README и Wiki объясняют назначение ролей и отсутствие обязательного линейного workflow.

**Технологии:** Python 3.10+, pytest, Markdown с YAML frontmatter, JSON Schema, CLI `agent-kit validate`.

**Спецификация:** `docs/superpowers/specs/2026-10-28-sdlc-agent-roles-design.md`.

## Общие ограничения

- Первый PR содержит только роли агентов, тесты, пользовательскую документацию и синхронное изменение версии.
- Skills и profiles не изменяются.
- Поля `role` и полное содержимое `agents/*.md` пишутся только на английском.
- Пользовательская документация пишется на русском.
- Роли не образуют обязательный линейный процесс и не получают подразумеваемого права на merge, deploy или внешние изменяющие действия.
- Логика `agent-kit project init` не изменяется.

---

### Задача 1: Зафиксировать расширенный обязательный набор тестом

**Файлы:**
- Изменить: `tests/test_repository.py`

**Интерфейсы:**
- Использует: `validate_agents(repository: Path) -> ValidationResult`.
- Производит: точный контракт из девяти default role IDs и обязательных разделов каждой роли.

- [ ] **Шаг 1: расширить существующий тест до девяти ролей**

Заменить ожидаемое множество в `test_default_agent_roles_are_complete_detailed_and_english` на:

```python
expected_roles = {
    "orchestrator",
    "requirements-analyst",
    "architect",
    "developer",
    "reviewer",
    "security-engineer",
    "qa-engineer",
    "evaluation-engineer",
    "release-engineer",
}
assert {path.stem for path in (repository / "agents").glob("*.md")} == expected_roles
```

В том же цикле добавить проверку общего контракта подробности:

```python
required_sections = (
    "## Mission",
    "## Use this role when",
    "## Required inputs",
    "## Responsibilities",
    "## Working method",
    "## Deliverables",
    "## Guardrails",
    "## Escalation and handoff",
    "## Completion criteria",
)
assert all(section in content for section in required_sections), path.name
```

- [ ] **Шаг 2: запустить тест и подтвердить ожидаемый RED**

Выполнить:

```bash
pytest tests/test_repository.py::test_default_agent_roles_are_complete_detailed_and_english -q
```

Ожидаемый результат: FAIL, потому что отсутствуют `requirements-analyst`, `security-engineer`, `evaluation-engineer` и `release-engineer`.

- [ ] **Шаг 3: закоммитить только failing contract test**

```bash
git add tests/test_repository.py
git commit -m "test(agents): define expanded sdlc role contract"
```

### Задача 2: Добавить четыре переносимые SDLC-роли

**Файлы:**
- Создать: `agents/requirements-analyst.md`
- Создать: `agents/security-engineer.md`
- Создать: `agents/evaluation-engineer.md`
- Создать: `agents/release-engineer.md`
- Изменить: `src/agent_engineering_kit/definitions.py`
- Тест: `tests/test_repository.py`

**Интерфейсы:**
- Использует: schema `schemas/agent.schema.json`, существующие model IDs и tool IDs.
- Производит: четыре role manifests и точный `DEFAULT_AGENT_IDS` из девяти элементов.

- [ ] **Шаг 1: создать роль Requirements Analyst**

Frontmatter должен использовать `id: requirements-analyst`, начинать `role` с `Analyze`, требовать `reasoning` и `long_context`, а в `tools` включать `code-search` и `mcp`. Текст должен раскрывать problem statement, scope, non-goals, stakeholders, assumptions, acceptance criteria, ambiguities, evidence, escalation и handoff архитектору/разработчику.

- [ ] **Шаг 2: создать роль Security Engineer**

Frontmatter должен использовать `id: security-engineer`, начинать `role` с `Assess`, требовать `reasoning`, `coding` и `tool_use`, а в `tools` включать `code-search`, `git-diff`, `tests` и `mcp`. Текст должен раскрывать assets, trust boundaries, data classification, abuse cases, secrets, access control, dependency/supply-chain risk, mitigations, residual risk и запрет на подмену общего code review.

- [ ] **Шаг 3: создать роль Evaluation Engineer**

Frontmatter должен использовать `id: evaluation-engineer`, начинать `role` с `Evaluate`, требовать `reasoning`, `coding` и `tool_use`, а в `tools` включать `tests` и `mcp`. Текст должен отделять deterministic tests от probabilistic evaluations и описывать traces, representative datasets, rubrics, baselines, thresholds, failure clusters, reproducibility и escalation при невалидной выборке.

- [ ] **Шаг 4: создать роль Release Engineer**

Frontmatter должен использовать `id: release-engineer`, начинать `role` с `Verify`, требовать `reasoning`, `coding` и `tool_use`, а в `tools` включать `tests`, `git-diff` и `mcp`. Текст должен описывать readiness evidence, compatibility, versioning, rollout, observability, rollback, change communication и явный запрет на merge/deploy без авторизации.

- [ ] **Шаг 5: обновить валидатор точного набора**

Заменить `DEFAULT_AGENT_IDS` на:

```python
DEFAULT_AGENT_IDS = frozenset({
    "orchestrator",
    "requirements-analyst",
    "architect",
    "developer",
    "reviewer",
    "security-engineer",
    "qa-engineer",
    "evaluation-engineer",
    "release-engineer",
})
```

Добавить `evaluate` в `_ENGLISH_ACTION_VERBS`, чтобы декларативное описание Evaluation Engineer проходило общую языковую эвристику.

- [ ] **Шаг 6: запустить focused tests и подтвердить GREEN**

```bash
pytest tests/test_repository.py::test_default_agent_roles_are_complete_detailed_and_english -q
pytest tests/test_repository.py::test_repository_passes_ci_validation -q
```

Ожидаемый результат: оба теста PASS; валидатор сообщает девять ролей.

- [ ] **Шаг 7: закоммитить роли и валидатор**

```bash
git add agents/requirements-analyst.md agents/security-engineer.md agents/evaluation-engineer.md agents/release-engineer.md src/agent_engineering_kit/definitions.py
git commit -m "feat(agents): add sdlc specialist roles"
```

### Задача 3: Обновить русскоязычную документацию набора ролей

**Файлы:**
- Изменить: `README.md`
- Изменить: `docs/wiki/Profiles-and-roles.md`
- Изменить: `docs/INDEX.md`

**Интерфейсы:**
- Использует: девять role IDs из задачи 2.
- Производит: единое пользовательское объяснение назначения ролей и их композиционного использования.

- [ ] **Шаг 1: обновить раздел README о ролях**

Заменить формулировку о пяти ролях на девять и добавить четыре пункта:

```markdown
- `requirements-analyst` — превращает исходный запрос в границы, non-goals и проверяемые критерии приёмки;
- `security-engineer` — анализирует assets, trust boundaries, abuse cases, секреты, доступ и supply-chain риски;
- `evaluation-engineer` — измеряет вероятностное поведение AI-агентов по traces, datasets, rubrics и baselines;
- `release-engineer` — собирает доказательства готовности, проверяет rollout, наблюдаемость и rollback без подразумеваемого права на публикацию.
```

После списка пояснить, что orchestrator выбирает минимально достаточный набор и роли не задают обязательный waterfall.

- [ ] **Шаг 2: синхронизировать Wiki**

В `docs/wiki/Profiles-and-roles.md` перечислить те же девять идентификаторов, кратко объяснить разделение Reviewer/Security/QA и QA/Evaluation, а также явно указать, что profile управляет возможностями harness и не равен роли.

- [ ] **Шаг 3: добавить план в индекс документации**

Добавить в `docs/INDEX.md` ссылку:

```markdown
- [План реализации базовых SDLC-ролей агентов](superpowers/plans/2026-10-28-sdlc-agent-roles.md).
```

- [ ] **Шаг 4: проверить русскоязычность Markdown**

```bash
pytest tests/test_repository.py::test_user_facing_markdown_files_are_written_in_russian -q
```

Ожидаемый результат: PASS; `agents/*.md` корректно исключены из требования русскоязычной прозы.

- [ ] **Шаг 5: закоммитить документацию**

```bash
git add README.md docs/wiki/Profiles-and-roles.md docs/INDEX.md docs/superpowers/plans/2026-10-28-sdlc-agent-roles.md
git commit -m "docs(agents): explain sdlc role composition"
```

### Задача 4: Синхронизировать feature-версию и выполнить полную проверку

**Файлы:**
- Изменить: `app.version`
- Изменить: `src/agent_engineering_kit/__init__.py`
- Изменить: `tests/test_documentation.py`

**Интерфейсы:**
- Использует: текущую версию `0.10.1`.
- Производит: согласованную feature-версию `0.11.0` во всех трёх источниках.

- [ ] **Шаг 1: сначала изменить ожидаемую версию в тесте**

В `test_release_version_is_synchronized` заменить обе строки `0.10.1` на `0.11.0`.

- [ ] **Шаг 2: подтвердить RED версии**

```bash
pytest tests/test_documentation.py::test_release_version_is_synchronized -q
```

Ожидаемый результат: FAIL, пока package metadata остаётся `0.10.1`.

- [ ] **Шаг 3: обновить фактическую версию**

Записать `0.11.0` в `app.version` и `__version__ = "0.11.0"` в `src/agent_engineering_kit/__init__.py`.

- [ ] **Шаг 4: подтвердить GREEN и выполнить полный quality gate**

```bash
pytest -q
agent-kit validate --ci
git diff --check origin/main...HEAD
```

Ожидаемый результат: все тесты PASS, validation завершён с `Результат: OK`, diff check не выводит ошибок.

- [ ] **Шаг 5: закоммитить версию**

```bash
git add app.version src/agent_engineering_kit/__init__.py tests/test_documentation.py
git commit -m "chore(release): bump version to 0.11.0"
```

- [ ] **Шаг 6: выполнить финальное независимое ревью перед PR**

Проверить diff относительно `origin/main`, отсутствие изменений в `profiles/` и `skills/`, затем открыть отдельный Pull Request для агентов. Merge разрешён только после успешного CI.
