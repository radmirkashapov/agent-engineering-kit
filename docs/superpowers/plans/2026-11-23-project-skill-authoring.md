# План реализации команд для добавления проектных навыков

> **Инструкция для агентов.** Для выполнения плана по задачам используйте `superpowers:subagent-driven-development` или `superpowers:executing-plans`. Отмечайте выполненные шаги в списке `- [ ]`.

**Цель.** Добавить безопасные команды для импорта корпоративных навыков и работы с отдельной Git-копией `project-skills`. Индексы помогут агентам находить проектные навыки и видеть итоговый набор.

**Архитектура.** Модуль `skill_authoring.py` проверяет пакет и рабочую копию Git, безопасно копирует файлы и составляет отслеживаемый индекс проекта. `projects.py` формирует манифест. `clients.py` составляет итоговый индекс по уже действующим приоритетам источников. `cli.py` разбирает аргументы и вызывает эти модули.

**Инструменты.** Python 3.10+, `argparse`, `pathlib`, `shutil`, `subprocess` через `run_command`, PyYAML и pytest.

[Дизайн команд и форматов](../specs/2026-11-23-project-skill-authoring-design.md)

## Общие ограничения

- Храните проектные навыки в отдельной рабочей копии. Запись в продуктовые репозитории и управляемую копию Kit запрещена.
- Создание ветки и удалённого репозитория, коммиты, push и PR/MR выполняются средствами Git и Git-платформы.
- Проверяйте `SKILL.md` по схеме `schemas/skill.schema.json` перед публикацией.
- ID навыка в источнике и назначении должны совпадать с именами соответствующих каталогов.
- Замена существующего каталога требует явного `--replace` и чистой рабочей копии.
- Пропускайте интерактивные вопросы при перенаправленном вводе и при явной передаче соответствующих параметров CLI.
- Пишите пользовательскую документацию и сообщения на русском языке.

---

### Задача 1. Безопасный импорт и отслеживаемый индекс проекта

**Файлы**
- Создать `src/agent_engineering_kit/skill_authoring.py`
- Проверить `tests/test_skill_authoring.py`

**Интерфейсы**
- Использует `LogicalProject`, `run_command`, `validate_skill_directory`, `atomic_write`.
- Предоставляет `add_bundled_skill(repository, source, identifier=None, replace=False) -> Path`, `checkout_project_skills(project, destination) -> Path`, `add_project_skill(repository, project, source, checkout, identifier=None, replace=False) -> Path` и `write_project_skill_index(repository, checkout) -> Path`.

- [ ] **Шаг 1. Написать тесты сервиса до реализации**

```python
def test_add_bundled_skill_copies_validated_directory(tmp_path, kit_repository):
    source = write_skill(tmp_path / "source", "review-api", "Review API changes.")
    target = add_bundled_skill(kit_repository, source)
    assert target == kit_repository / "skills/first-party/review-api"
    assert (target / "SKILL.md").is_file()

def test_project_skill_checkout_rejects_product_repository(fixture):
    with pytest.raises(AgentKitError, match="product repository"):
        add_project_skill(fixture.repository, fixture.project, fixture.source, fixture.project.root)

def test_add_project_skill_writes_deterministic_index(fixture):
    checkout = fixture.clone_sibling()
    add_project_skill(fixture.repository, fixture.project, fixture.source, checkout)
    assert "review-api" in (checkout / "skills/INDEX.md").read_text(encoding="utf-8")
```

- [ ] **Шаг 2. Подтвердить ожидаемое падение тестов**

Команда проверки. `uv run --extra dev pytest tests/test_skill_authoring.py -q`

Ожидаемый результат. Сбор тестов прерывается из-за отсутствующего модуля `agent_engineering_kit.skill_authoring`.

- [ ] **Шаг 3. Реализовать сервис**

```python
def add_bundled_skill(repository: Path, source: Path, *, identifier: str | None = None, replace: bool = False) -> Path:
    resolved = _validated_source(repository, source, identifier)
    return _copy_skill(resolved.source, repository / "skills" / "first-party" / resolved.identifier, replace=replace)

def write_project_skill_index(repository: Path, checkout: Path) -> Path:
    skills = _project_skill_directories(repository, checkout)
    rows = [f"| `{item.identifier}` | {item.description} | `{item.identifier}/SKILL.md` |" for item in skills]
    target = checkout / "skills" / "INDEX.md"
    atomic_write(target, "# Project skills\\n\\n| ID | Назначение | Определение |\\n|---|---|---|\\n" + "\\n".join(rows) + "\\n")
    return target
```

Проверяйте, что исходный и целевой каталоги обычные и не являются символическими ссылками, нормализованные URL `origin` и манифеста совпадают, а каталог для клонирования пуст. Для замены отслеживаемого навыка с `--replace` требуйте чистый `git status --porcelain`. Подготовьте копию во временном соседнем каталоге и замените исходный пакет атомарно после проверки.

- [ ] **Шаг 4. Подтвердить успешное прохождение тестов**

Команда проверки. `uv run --extra dev pytest tests/test_skill_authoring.py -q`

Ожидаемый результат. Проходят все новые модульные тесты и тесты с временными Git-репозиториями.

- [ ] **Шаг 5. Создать коммит**

```bash
git add src/agent_engineering_kit/skill_authoring.py tests/test_skill_authoring.py
git commit -m "feat(skills): add safe skill authoring service"
```

### Задача 2. Настройка проектных навыков при инициализации

**Файлы**
- Изменить `src/agent_engineering_kit/projects.py`
- Изменить `src/agent_engineering_kit/cli.py`
- Изменить `tests/test_projects.py`
- Изменить `tests/test_cli.py`

**Интерфейсы**
- Использует `init_project(..., skills_repository_url: str | None, skills_default_branch: str = "main")`.
- Формирует необязательную секцию `skills.repository` в манифесте и проверяет её.

- [ ] **Шаг 1. Написать тесты инициализации и CLI до реализации**

```python
def test_project_init_records_explicit_skills_repository(tmp_path, kit_repository):
    project = init_project(tmp_path / "demo", kit_repository, paths(tmp_path, kit_repository),
                           skills_repository_url="git@gitlab.example:team/demo-skills.git")
    assert project.skills_repository == {"url": "git@gitlab.example:team/demo-skills.git", "default_branch": "main"}

def test_project_init_parses_skills_repository_arguments():
    args = _parser().parse_args(["project", "init", "--skills-repository-url", "git@gitlab.example:team/demo-skills.git"])
    assert args.skills_repository_url.endswith("demo-skills.git")

def test_interactive_project_init_prompts_for_skills_repository(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "git@gitlab.example:team/demo-skills.git")
    assert _interactive_project_setup(REPOSITORY)["skills_repository_url"].endswith("demo-skills.git")

def test_project_init_keeps_full_codebase_memory_and_serena_indexing(tmp_path, kit_repository, monkeypatch):
    calls = []
    monkeypatch.setattr(projects_module.ProjectMemoryManager, "index", lambda _self, _project, *, mode: calls.append(mode) or {"status": "PASS"})
    init_project(tmp_path / "demo", kit_repository, paths(tmp_path, kit_repository))
    assert calls == ["full"]
```

- [ ] **Шаг 2. Подтвердить ожидаемое падение тестов**

Команда проверки. `uv run --extra dev pytest tests/test_projects.py tests/test_cli.py -k 'skills_repository or interactive_project' -q`

Ожидаемый результат. Тесты выявляют неизвестный именованный аргумент `init_project` и отсутствующие параметры CLI.

- [ ] **Шаг 3. Записывать источник в манифест и обрабатывать интерактивный ввод**

Добавьте `--skills-repository-url` и `--skills-default-branch` к `project init`. Для передачи ветки требуется URL. Расширьте `_interactive_project_setup()` одним необязательным вопросом об URL после выбора Git. Для введённого URL используйте ветку `main` по умолчанию. Передайте значения в `init_project()`, который добавляет `skills.repository` до проверки схемы. Сохраните идемпотентность инициализации. Задавайте вопрос только при вводе через TTY.

После создания манифеста сохраните единственный вызов `ProjectMemoryManager.index(project, mode="full")`. Отдельный тест должен подтвердить, что по-прежнему запрашивается полная индексация.

- [ ] **Шаг 4. Подтвердить успешное прохождение тестов**

Команда проверки. `uv run --extra dev pytest tests/test_projects.py tests/test_cli.py -k 'skills_repository or interactive_project' -q`

Ожидаемый результат. Все выбранные тесты проходят.

- [ ] **Шаг 5. Создать коммит**

```bash
git add src/agent_engineering_kit/projects.py src/agent_engineering_kit/cli.py tests/test_projects.py tests/test_cli.py
git commit -m "feat(projects): configure project skill repositories at init"
```

### Задача 3. Команды импорта и индекс доступных навыков

**Файлы**
- Изменить `src/agent_engineering_kit/cli.py`
- Изменить `src/agent_engineering_kit/clients.py`
- Изменить `tests/test_cli.py`
- Изменить `tests/test_clients.py`

**Интерфейсы**
- Использует сервис из задачи 1 и `effective_skill_sources()`.
- Предоставляет `agent-kit skills add` и `agent-kit project skills checkout|add|index`. Сохраняет `effective-skills.md` рядом с `skills-provenance.json`.

- [ ] **Шаг 1. Написать тесты CLI и индекса до реализации**

```python
def test_skill_add_invokes_bundled_authoring(isolated_data, monkeypatch, capsys):
    monkeypatch.setattr(cli_module, "add_bundled_skill", lambda *_args, **_kwargs: Path("/kit/skills/first-party/review-api"))
    assert run(["skills", "add", "--from", "source"]) == 0
    assert "review-api" in capsys.readouterr().out

def test_project_skills_checkout_and_add_are_in_parser():
    assert _parser().parse_args(["project", "skills", "checkout", "--into", "../project-skills"]).project_skills_command == "checkout"
    assert _parser().parse_args(["project", "skills", "add", "--from", "source", "--checkout", "../project-skills"]).project_skills_command == "add"

def test_client_sync_writes_effective_skill_index(publication_fixture):
    sync_clients(publication_fixture.paths.repository, publication_fixture.paths, project=publication_fixture.project)
    index = publication_fixture.paths.installations / "clients/shared/effective-skills.md"
    assert "project-skills" in index.read_text(encoding="utf-8")

def test_resync_keeps_native_mcp_when_docker_is_unavailable(paths, monkeypatch):
    monkeypatch.setattr("agent_engineering_kit.docker_mcp.shutil.which", lambda _: None)
    assert resync(REPOSITORY, paths, update_kit=False).mcp
```

- [ ] **Шаг 2. Подтвердить ожидаемое падение тестов**

Команда проверки. `uv run --extra dev pytest tests/test_cli.py tests/test_clients.py -k 'skill_add or project_skills_checkout or effective_skill_index' -q`

Ожидаемый результат. Проверки выявляют отсутствие команд и генерируемого Markdown.

- [ ] **Шаг 3. Подключить команды и генерацию индекса**

Добавьте параметры и диспетчеризацию CLI. Перед вызовом сервиса найдите и проверьте текущий логический проект. Выведите пути изменённых файлов. В `sync_clients()` сформируйте по одной детерминированной строке Markdown на `EffectiveSkillSource` с ID, `description`, источником, состоянием, ревизией и именами вытесненных источников. Атомарно запишите индекс в `shared.parent / "effective-skills.md"` и добавьте его путь в сгенерированный адаптер.

Docker MCP Toolkit остаётся необязательным при `resync`. Если Docker или Toolkit недоступен либо ранее применённый профиль не проходит проверку, восстановите нативную маршрутизацию MCP и сообщите о пропуске Toolkit. Ошибки обязательной нативной установки или регистрации MCP должны прерывать синхронизацию.

- [ ] **Шаг 4. Подтвердить успешное прохождение тестов**

Команда проверки. `uv run --extra dev pytest tests/test_cli.py tests/test_clients.py -k 'skill_add or project_skills_checkout or effective_skill_index' -q`

Ожидаемый результат. Все выбранные тесты проходят.

- [ ] **Шаг 5. Создать коммит**

```bash
git add src/agent_engineering_kit/cli.py src/agent_engineering_kit/clients.py tests/test_cli.py tests/test_clients.py
git commit -m "feat(skills): expose project skill authoring commands"
```

### Задача 4. Документация и проверка рабочего процесса

**Файлы**
- Изменить `docs/runbooks/corporate-extensions-and-mcp-credentials.md`
- Изменить `docs/wiki/Project-skills.md`
- Изменить `docs/wiki/CLI.md`
- Изменить `README.md`
- Изменить `docs/INDEX.md`
- Проверить `tests/test_repository.py`
- Проверить `tests/test_documentation.py`

**Интерфейсы**
- Использует итоговый интерфейс CLI и приоритет источников.
- Публикует русскоязычное руководство и связывает дизайн и план с индексом.

- [ ] **Шаг 1. Зафиксировать проверку списка команд в руководстве**

```python
def test_project_skills_guide_lists_authoring_commands():
    guide = (REPOSITORY / "docs/wiki/Project-skills.md").read_text(encoding="utf-8")
    assert "project skills checkout" in guide
    assert "project skills add" in guide
```

- [ ] **Шаг 2. Подтвердить ожидаемое падение тестов**

Команда проверки. `uv run --extra dev pytest tests/test_repository.py tests/test_documentation.py -k 'project_skills_guide' -q`

Ожидаемый результат. Новая проверка выявляет отсутствие команд до обновления руководства.

- [ ] **Шаг 3. Обновить документацию и индексы**

Опишите работу с отдельной Git-копией, новые команды и флаги, отслеживаемый `skills/INDEX.md` и генерируемый `effective-skills.md`. Укажите, что управляемое хранилище закрыто для редактирования навыков. При импорте обычное дерево пакета копируется целиком. `SKILL.md` может ссылаться на Markdown-файлы шагов и вложенные каталоги контрактов и спецификаций. Относительные ссылки внутри пакета продолжают работать, а символические ссылки отклоняются. Опишите необязательную интеграцию Docker MCP Toolkit, возврат к нативной маршрутизации и сообщение о пропуске при недоступном Toolkit или непригодном профиле. Укажите относительную ссылку на план в `docs/INDEX.md`.

- [ ] **Шаг 4. Запустить весь набор регрессионных тестов и проверок**

Run:

```bash
uv run --extra dev pytest
uv run --extra dev agent-kit validate --ci
git diff --check
```

Ожидаемый результат. Тесты и проверка CI проходят, а Git не находит ошибок пробелов.

- [ ] **Шаг 5. Создать коммит**

```bash
git add README.md docs tests
git commit -m "docs(skills): document skill authoring workflow"
```
