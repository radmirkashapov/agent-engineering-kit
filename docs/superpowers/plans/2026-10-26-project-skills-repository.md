# План реализации репозитория проектных skills

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Цель:** Подключить к logical project единый Git-репозиторий skills, автоматически обновлять проверенную ревизию из `main` и разрешить machine-local выбор удалённой ветки.

**Архитектура:** Новый `ProjectSkillRepositoryManager` управляет только machine-local checkout, candidate-проверкой и атомарным указателем активной ревизии. `.ai-team/project.yaml` хранит URL и default branch, `project.id` объединяет несколько продуктовых репозиториев, а существующие `resync`, security pipeline и thin adapters получают дополнительный источник skills без копирования в продуктовые repositories.

**Технологии:** Python 3.10+, argparse, pathlib, subprocess через существующий `run_command`, JSON Schema Draft 2020-12, PyYAML, pytest, Git CLI.

**Спецификация:** `docs/superpowers/specs/2026-10-26-project-skills-repository-design.md`

## Общие ограничения

- Единственный источник проектных skills — отдельный обычный Git-репозиторий `project-skills`; копии в продуктовых repositories запрещены.
- `main` используется по умолчанию; machine-local branch override применяется ко всем repositories с тем же `project.id` и игнорируется в CI.
- Agent Engineering Kit не создаёт ветки, commits, push, PR/MR и не подключает пользовательский local checkout.
- Candidate становится active только после структурной и security-проверки; ошибка сохраняет last-known-good revision.
- Git credentials остаются в SSH agent или credential helper и никогда не записываются в runtime manifests и status.
- YAML-комментарии, кодовые комментарии и пользовательская документация пишутся на профессиональном русском; default descriptions ролей, skills и MCP остаются на английском.
- Все изменения выполняются через TDD, отдельные Conventional Commits и итоговый Pull Request; прямой push в `main` запрещён.
- Версия `app.version` и `src/agent_engineering_kit/__init__.py` меняется синхронно в финальной задаче.

## Карта файлов

- `src/agent_engineering_kit/project_skills.py` — конфигурация источника, Git fetch, branch override, блокировка, candidate validation, active state и status/provenance.
- `src/agent_engineering_kit/projects.py` — безопасное совместное использование namespace несколькими repositories с одной ссылкой на `project-skills`.
- `src/agent_engineering_kit/resync.py` — обновление project skills до формирования effective policy и session manifest.
- `src/agent_engineering_kit/clients.py` — добавление активных project skills в общий каталог thin adapters с детекцией коллизий.
- `src/agent_engineering_kit/cli.py` — `agent-kit project skills use-branch|use-main|status`.
- `schemas/project.schema.json` и `templates/project/project.yaml` — декларативный контракт источника skills.
- `tests/test_project_skills.py` — Git lifecycle, безопасность, offline fallback, locking и status.
- `tests/test_projects.py`, `tests/test_clients.py`, `tests/test_resync.py`, `tests/test_cli.py` — интеграционные границы.
- `README.md`, `docs/INDEX.md` — эксплуатация и диагностика.

---

### Задача 1: Контракт manifest и общий namespace проекта

**Файлы:**
- Изменить: `schemas/project.schema.json`
- Изменить: `templates/project/project.yaml`
- Изменить: `src/agent_engineering_kit/projects.py`
- Изменить: `tests/test_projects.py`

**Интерфейсы:**
- Использует: `LogicalProject.manifest`, `validate_instance()`, `register_memory()`.
- Предоставляет: `LogicalProject.skills_repository -> dict[str, str] | None`; identity-документ с `project_id`, `skills_repository_url` и `root_hashes`.

- [ ] **Шаг 1: Написать падающие тесты manifest и namespace**

Добавить тесты безопасного источника, запрета URL с credentials, сохранения защиты от коллизии без источника и разрешения двух roots только с одинаковым источником:

```python
def _skills_source(project, url="git@gitlab.example.com:team/project-skills.git"):
    project.manifest["skills"] = {"repository": {"url": url, "default_branch": "main"}}
    return project


def test_project_manifest_accepts_project_skills_repository(tmp_path, kit_repository):
    project = _skills_source(init_project(tmp_path / "first", kit_repository, paths(tmp_path, kit_repository)))
    assert validate_project(project, kit_repository).ok
    assert project.skills_repository == {
        "url": "git@gitlab.example.com:team/project-skills.git",
        "default_branch": "main",
    }


def test_shared_project_id_requires_identical_skills_source(tmp_path, kit_repository):
    kit_paths = paths(tmp_path, kit_repository)
    source = {"repository": {"url": "git@gitlab.example.com:team/project-skills.git", "default_branch": "main"}}
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first = LogicalProject(first_root, first_root / ".ai-team/project.yaml", {
        "version": 1, "id": "shared", "name": "First", "repositories": [{"id": "root", "path": "."}],
        "documentation": {"index": "docs/INDEX.md", "roots": ["docs"]},
        "memory": {"namespace": "shared"}, "skills": source,
    })
    second = LogicalProject(second_root, second_root / ".ai-team/project.yaml", {
        **first.manifest, "name": "Second",
    })
    register_memory(first, kit_paths)
    register_memory(second, kit_paths)
    assert len(json.loads((kit_paths.projects / "shared/identity.json").read_text())["root_hashes"]) == 2


@pytest.mark.parametrize("url", [
    "https://user:secret@example.com/project-skills.git",
    "https://example.com/project-skills.git?token=secret",
])
def test_project_skills_url_rejects_credentials(tmp_path, kit_repository, url):
    project = _skills_source(init_project(tmp_path / "unsafe", kit_repository, paths(tmp_path, kit_repository)), url)
    assert not validate_project(project, kit_repository).ok
```

- [ ] **Шаг 2: Запустить сфокусированные тесты и подтвердить падение**

Команда: `pytest tests/test_projects.py -k 'project_skills or shared_project_id' -v`

Ожидается: FAIL, потому что schema отклоняет `skills`, свойство `skills_repository` отсутствует, а текущий identity-контракт разрешает только один root.

- [ ] **Шаг 3: Расширить schema и шаблон**

Добавить необязательный `skills.repository` с обязательными `url` и `default_branch`. Повторно использовать существующее ограничение безопасного URL и ограничить имя ветки непустым Git ref без пробелов и `..`:

```json
"skills": {
  "type": "object",
  "required": ["repository"],
  "additionalProperties": false,
  "properties": {
    "repository": {
      "type": "object",
      "required": ["url", "default_branch"],
      "additionalProperties": false,
      "properties": {
        "url": {"type": "string", "minLength": 1, "not": {"pattern": "(?:[?#]|://[^/]*@)"}},
        "default_branch": {"type": "string", "pattern": "^(?!.*\\.\\.)(?!.*\\s)[^~^:?*\\\\[]+$"}
      }
    }
  }
}
```

Добавить закомментированный выключенный пример в `templates/project/project.yaml`; отсутствие секции означает `NOT_CONFIGURED` и не должно создавать вымышленный URL репозитория.

- [ ] **Шаг 4: Реализовать доступ к настройке и совместимую регистрацию namespace**

Добавить свойство:

```python
@property
def skills_repository(self) -> dict[str, str] | None:
    value = self.manifest.get("skills", {}).get("repository")
    return dict(value) if isinstance(value, dict) else None
```

Изменить `register_memory()`: второй root принимается только при одинаковом непустом нормализованном URL источника в обоих identities. Сохранять отсортированный уникальный набор SHA-256 hashes корней. Сохранить существующую ошибку коллизии для отсутствующих или разных источников.

- [ ] **Шаг 5: Запустить тесты и сделать commit**

Команда: `pytest tests/test_projects.py -v`

Ожидается: PASS.

```bash
git add schemas/project.schema.json templates/project/project.yaml src/agent_engineering_kit/projects.py tests/test_projects.py
git commit -m "feat(projects): declare shared project skills source"
```

### Задача 2: Управляемый Git checkout и выбор ветки

**Файлы:**
- Создать: `src/agent_engineering_kit/project_skills.py`
- Создать: `tests/test_project_skills.py`

**Интерфейсы:**
- Использует: `LogicalProject.skills_repository`, `KitPaths.projects`, `KitPaths.locks`, `run_command()`, `atomic_write()`.
- Предоставляет: `ProjectSkillRepositoryManager.set_branch(branch: str) -> dict[str, object]`, `use_main() -> dict[str, object]`, `requested_branch(ci: bool = False) -> str`, `fetch_candidate(ci: bool = False) -> tuple[Path, str]`.

- [ ] **Шаг 1: Написать падающие тесты жизненного цикла Git**

Создать локальный bare upstream с `main` и `feat/new-check`; проверить выбор по умолчанию, общий сохранённый override для двух объектов `LogicalProject` с одинаковым id, `use_main` и поведение при отсутствующей ветке:

```python
def test_branch_override_is_machine_local_and_shared_by_project_id(fixture):
    manager = fixture.manager()
    assert manager.requested_branch() == "main"
    manager.set_branch("feat/new-check")
    assert fixture.manager(second_root=True).requested_branch() == "feat/new-check"
    assert manager.requested_branch(ci=True) == "main"
    assert not (fixture.project.root / ".ai-team/project-skills-branch").exists()
    manager.use_main()
    assert manager.requested_branch() == "main"


def test_fetch_candidate_resolves_remote_commit_without_touching_product_tree(fixture):
    before = fixture.product_head()
    candidate, revision = fixture.manager().fetch_candidate()
    assert revision == fixture.remote_revision("main")
    assert (candidate / "skills/example/SKILL.md").is_file()
    assert fixture.product_head() == before
```

- [ ] **Шаг 2: Запустить новые тесты и подтвердить ошибку импорта**

Команда: `pytest tests/test_project_skills.py -k 'branch_override or fetch_candidate' -v`

Ожидается: FAIL с `ModuleNotFoundError: agent_engineering_kit.project_skills`.

- [ ] **Шаг 3: Реализовать пути, проверку ref и локальный override**

Определить сфокусированные неизменяемые типы и методы путей:

```python
@dataclass(frozen=True)
class ProjectSkillsSource:
    url: str
    default_branch: str


class ProjectSkillRepositoryManager:
    def __init__(self, repository: Path, paths: KitPaths, project: LogicalProject,
                 *, validator: SkillValidator | None = None,
                 runner: Callable[..., CommandResult] = run_command) -> None:
        self.repository = repository
        self.paths = paths
        self.project = project
        self.runner = runner
        self.validator = validator or SecurityToolManager(repository, paths).validate_skill

    @property
    def root(self) -> Path:
        return self.paths.projects / self.project.identifier / "skills-repository"

    def requested_branch(self, *, ci: bool = False) -> str:
        source = self.source()
        if ci or not self.override_path.is_file():
            return source.default_branch
        return str(load_json(self.override_path)["branch"])

    def set_branch(self, branch: str) -> dict[str, object]:
        checked = self.runner(["git", "check-ref-format", "--branch", branch])
        if not checked.ok:
            raise AgentKitError("Некорректное имя ветки project-skills")
        atomic_write(self.override_path, json.dumps({"branch": branch}) + "\n")
        os.chmod(self.override_path, 0o600)
        return self.status().as_dict()

    def use_main(self) -> dict[str, object]:
        self.override_path.unlink(missing_ok=True)
        return self.status().as_dict()
```

Хранить override в `root/branch-override.json` с режимом `0600`. До записи проверять через `git check-ref-format --branch`. Значение `ci=True` должно возвращать `default_branch` без чтения override.

- [ ] **Шаг 4: Реализовать сериализованные fetch и detached candidate**

Использовать `paths.locks / f"project-skills-{project.identifier}.lock"` и уже применённый в `tasks.py` паттерн блокировки. Под блокировкой выполнить:

```python
git clone --quiet --no-checkout <url> <root>/checkout
git -C <root>/checkout remote set-url origin <url>
git -C <root>/checkout fetch --quiet --prune origin <branch>
git -C <root>/checkout rev-parse refs/remotes/origin/<branch>
git -C <root>/checkout worktree add --detach <candidate> <sha>
```

Никогда не интерполировать ветку в shell-строку; передавать каждый аргумент списком. Маскировать URL в исключениях функцией `redact_url()` нового модуля.

- [ ] **Шаг 5: Запустить тесты и сделать commit**

Команда: `pytest tests/test_project_skills.py -k 'branch_override or fetch_candidate' -v`

Ожидается: PASS.

```bash
git add src/agent_engineering_kit/project_skills.py tests/test_project_skills.py
git commit -m "feat(skills): manage project skills checkout"
```

### Задача 3: Проверка candidate и активация last-known-good

**Файлы:**
- Изменить: `src/agent_engineering_kit/project_skills.py`
- Изменить: `tests/test_project_skills.py`

**Интерфейсы:**
- Использует: сигнатуру validator `Callable[[Path], tuple[bool, list[dict[str, Any]]]]`; значение по умолчанию — `SecurityToolManager(repository, paths).validate_skill`.
- Предоставляет: `ProjectSkillsStatus`, `ProjectSkillRepositoryManager.resync(ci: bool = False) -> ProjectSkillsStatus`, `active_skills() -> dict[str, Path]`, `status() -> ProjectSkillsStatus`.

- [ ] **Шаг 1: Написать падающие тесты активации**

Покрыть первый успех, идемпотентное обновление, отклонённое обновление с сохранением предыдущего SHA, некорректный skill, offline fallback и параллельные вызовы:

```python
def test_rejected_update_keeps_last_known_good(fixture):
    manager = fixture.manager(validator=lambda _: (True, [{"check": "fixture", "status": "PASS"}]))
    active = manager.resync()
    fixture.commit_skill("main", description="Rejected revision")
    manager.validator = lambda _: (False, [{"check": "fixture", "status": "FAIL"}])
    rejected = manager.resync()
    assert rejected.state == "UPDATE_REJECTED"
    assert rejected.active_revision == active.active_revision
    assert manager.active_skills()["example"].joinpath("SKILL.md").is_file()


def test_offline_refresh_reports_stale_and_keeps_active_revision(fixture):
    manager = fixture.manager(validator=lambda _: (True, []))
    active = manager.resync()
    fixture.disable_remote()
    stale = manager.resync()
    assert stale.state == "STALE"
    assert stale.active_revision == active.active_revision
```

- [ ] **Шаг 2: Подтвердить падение тестов жизненного цикла**

Команда: `pytest tests/test_project_skills.py -k 'known_good or offline or concurrent or malformed' -v`

Ожидается: FAIL, потому что активация и status ещё не существуют.

- [ ] **Шаг 3: Реализовать структурную проверку**

Требовать каталог `skills/`, минимум один дочерний каталог, один `SKILL.md` в каждом дочернем каталоге, закрытый YAML frontmatter и `name`, совпадающий с именем каталога. Отклонять symlink за пределы candidate и повторяющиеся skill ids. Возвращать явные evidence-записи вместо голых boolean.

- [ ] **Шаг 4: Реализовать атомарную активацию и status**

Define:

```python
@dataclass(frozen=True)
class ProjectSkillsStatus:
    project_id: str
    source_url: str | None
    default_branch: str | None
    requested_branch: str | None
    resolved_revision: str | None
    active_revision: str | None
    state: Literal["ACTIVE", "STALE", "UPDATE_REJECTED", "NOT_CONFIGURED"]
    reason: str | None
    updated_at: str | None
    skills: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "source_url": redact_url(self.source_url),
            "default_branch": self.default_branch,
            "requested_branch": self.requested_branch,
            "resolved_revision": self.resolved_revision,
            "active_revision": self.active_revision,
            "state": self.state,
            "reason": self.reason,
            "updated_at": self.updated_at,
            "skills": list(self.skills),
        }
```

Переместить проверенный candidate в `root/revisions/<sha>`, затем атомарно записать `root/active.json`. При ошибке fetch и наличии active revision вернуть `STALE`; при ошибке проверки — `UPDATE_REJECTED`; без конфигурации — `NOT_CONFIGURED`; без какой-либо active revision выбросить `AgentKitError`.

- [ ] **Шаг 5: Запустить тесты жизненного цикла и сделать commit**

Команда: `pytest tests/test_project_skills.py -v`

Ожидается: PASS.

```bash
git add src/agent_engineering_kit/project_skills.py tests/test_project_skills.py
git commit -m "feat(skills): activate validated project skills"
```

### Задача 4: Приоритет effective skills и публикация в клиенты

**Файлы:**
- Изменить: `src/agent_engineering_kit/clients.py`
- Изменить: `tests/test_clients.py`
- Изменить: `tests/test_project_skills.py`

**Интерфейсы:**
- Использует: `ProjectSkillRepositoryManager.active_skills() -> dict[str, Path]` и существующие external/local источники skills.
- Предоставляет: `sync_clients(repository: Path, paths: KitPaths, *, project: LogicalProject | None = None, capability_policy: dict | None = None) -> list[Path]`; provenance-файл `installations/clients/shared/skills-provenance.json`.

- [ ] **Шаг 1: Написать падающие тесты приоритета и provenance**

```python
def test_project_skills_are_published_with_provenance(tmp_path, project_fixture):
    manager = project_fixture.manager(validator=lambda _: (True, []))
    status = manager.resync()
    sync_clients(project_fixture.repository, project_fixture.paths, project=project_fixture.project)
    shared = project_fixture.paths.installations / "clients/shared"
    assert (shared / "skills/example").resolve() == manager.active_skills()["example"].resolve()
    provenance = json.loads((shared / "skills-provenance.json").read_text())
    assert provenance["skills"]["example"]["source"] == "project-skills"
    assert provenance["skills"]["example"]["revision"] == status.active_revision
```

Добавить коллизии built-in/external/project/local источников и проверить документированный порядок победителей: built-in, external catalog, project repository, затем явно разрешённый local override.

- [ ] **Шаг 2: Запустить тесты и подтвердить падение**

Команда: `pytest tests/test_clients.py -k 'project_skills or provenance or precedence' -v`

Ожидается: FAIL, потому что у `sync_clients` нет параметра `project` и вывода provenance.

- [ ] **Шаг 3: Перестроить сбор источников skills без изменения adapters**

Ввести внутреннюю запись и единственную функцию разрешения:

```python
@dataclass(frozen=True)
class EffectiveSkillSource:
    identifier: str
    path: Path
    source: str
    revision: str | None
    priority: int


def _merge_skill_source(target: dict[str, EffectiveSkillSource], candidate: EffectiveSkillSource) -> None:
    current = target.get(candidate.identifier)
    if current is None or candidate.priority >= current.priority:
        target[candidate.identifier] = candidate
```

Использовать приоритеты: `10` для built-in, `20` для external catalog, `30` для project-skills, `40` для local override. Сохранять provenance коллизии с выбранным и затенённым источниками; никогда не объединять содержимое файлов.

- [ ] **Шаг 4: Опубликовать project skills и provenance**

Изменить `sync_clients` и `expose_native_skills`, чтобы они принимали `project: LogicalProject | None`. Внутри `sync_clients` вычислять `project_id = project.identifier if project else None` и сохранить существующую защиту managed links от коллизий. Атомарно записывать provenance с замаскированным URL источника и точной active revision.

- [ ] **Шаг 5: Запустить тесты клиентов и сделать commit**

Команда: `pytest tests/test_clients.py tests/test_project_skills.py -v`

Ожидается: PASS.

```bash
git add src/agent_engineering_kit/clients.py tests/test_clients.py tests/test_project_skills.py
git commit -m "feat(clients): publish project skills with provenance"
```

### Задача 5: Интеграция с resync и session manifest

**Файлы:**
- Изменить: `src/agent_engineering_kit/resync.py`
- Изменить: `tests/test_resync.py`

**Интерфейсы:**
- Использует: `ProjectSkillRepositoryManager.resync()`, `sync_clients(repository, paths, project=project)`, `expose_native_skills(repository, paths, project=project)`.
- Предоставляет: `ResyncReport.project_skills: dict[str, object] | None`; поле `project_skills` в session manifest.

- [ ] **Шаг 1: Написать падающие тесты оркестрации**

```python
def test_resync_updates_project_skills_before_client_sync(monkeypatch, project_fixture):
    calls = []
    class FakeProjectSkills:
        def resync(self):
            calls.append("project-skills")
            return SimpleNamespace(as_dict=lambda: {
                "state": "ACTIVE", "requested_branch": "main",
                "resolved_revision": "abc123", "active_revision": "abc123",
            })

    monkeypatch.setattr(resync_module, "ProjectSkillRepositoryManager", lambda *a, **k: FakeProjectSkills())
    monkeypatch.setattr(resync_module, "validate", lambda *a, **k: SimpleNamespace(ok=True))
    monkeypatch.setattr(resync_module, "validate_overrides", lambda *a, **k: SimpleNamespace(ok=True))
    monkeypatch.setattr(resync_module, "initialize_override_workspace", lambda *a, **k: None)
    monkeypatch.setattr(resync_module, "ensure_runtime", lambda *a, **k: None)
    monkeypatch.setattr(resync_module, "revision", lambda *a, **k: "kit123")
    monkeypatch.setattr(resync_module.ExternalSkillManager, "resync", lambda self, **kwargs: [])
    monkeypatch.setattr(resync_module, "sync_clients", lambda *a, **k: calls.append("clients") or [])
    monkeypatch.setattr(resync_module, "resolve_effective_policy", lambda *a, **k: SimpleNamespace(
        values={"mcp.access_profile": "readonly"}, as_dict=lambda: {},
    ))
    monkeypatch.setattr(resync_module.McpManager, "install", lambda self, **kwargs: SimpleNamespace(ok=True))
    monkeypatch.setattr(resync_module.McpManager, "list", lambda self, *a, **k: [])
    report = resync_module.resync(
        project_fixture.repository, project_fixture.paths,
        project=project_fixture.project, update_kit=False,
        install_security=False, expose_native=False,
    )
    assert calls.index("project-skills") < calls.index("clients")
    assert report.project_skills["state"] == "ACTIVE"


def test_session_manifest_records_project_skills(tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text("{}\n", encoding="utf-8")
    project_skills = {
        "state": "ACTIVE", "requested_branch": "main",
        "resolved_revision": "abc123", "active_revision": "abc123",
    }
    manifest = build_session_manifest(
        revision="kit123", project_id="demo", security=[], skills=[], mcp=[], clients=[],
        harness={}, effective_policy=policy, recorded_at="2026-10-26T00:00:00+03:00",
        project_skills=project_skills,
    )
    assert manifest["project_skills"] == project_skills
```

Добавить параметризованные случаи resync `NOT_CONFIGURED` и `STALE`, которые возвращают отчёт, а также fake manager, выбрасывающий `AgentKitError("initial fetch failed")`; проверить распространение ошибки при отсутствии active revision.

- [ ] **Шаг 2: Подтвердить падение тестов оркестрации**

Команда: `pytest tests/test_resync.py -k project_skills -v`

Ожидается: FAIL, потому что у `ResyncReport` и `build_session_manifest` нет поля project skills.

- [ ] **Шаг 3: Интегрировать manager до синхронизации клиентов**

Создавать manager только при наличии `LogicalProject`. Вызвать `resync()`, передать полный project в функции клиентов и включить `status.as_dict()` в `ResyncReport` и `effective-environment.json`. Не завершаться ошибкой при `STALE` или `NOT_CONFIGURED`; manager сам выбрасывает исключение, если безопасной active revision нет.

- [ ] **Шаг 4: Запустить тесты resync и сделать commit**

Команда: `pytest tests/test_resync.py tests/test_clients.py -v`

Ожидается: PASS.

```bash
git add src/agent_engineering_kit/resync.py tests/test_resync.py
git commit -m "feat(resync): refresh project skills repository"
```

### Задача 6: CLI и help для project skills

**Файлы:**
- Изменить: `src/agent_engineering_kit/cli.py`
- Изменить: `tests/test_cli.py`

**Интерфейсы:**
- Использует: `find_project(Path.cwd())`, `ProjectSkillRepositoryManager.set_branch()`, `use_main()`, `status()`.
- Предоставляет: `agent-kit project skills use-branch <branch>`, `use-main` и `status`; JSON status с замаскированным URL.

- [ ] **Шаг 1: Написать падающие тесты parser и команд**

```python
def test_project_skills_commands_are_in_help():
    parser = cli._parser()
    assert parser.parse_args(["project", "skills", "use-branch", "feat/check"]).project_skills_command == "use-branch"
    assert parser.parse_args(["project", "skills", "use-main"]).project_skills_command == "use-main"
    assert parser.parse_args(["project", "skills", "status"]).project_skills_command == "status"


def test_project_skills_requires_logical_project(monkeypatch, capsys):
    monkeypatch.setattr(cli, "find_project", lambda _: None)
    assert cli.run(["project", "skills", "status"]) == 1
    assert "logical project" in capsys.readouterr().err
```

Добавить тесты команд с fake manager и проверить, что вывод ветки, URL и ошибки никогда не содержат встроенные credentials.

- [ ] **Шаг 2: Подтвердить падение тестов CLI**

Команда: `pytest tests/test_cli.py -k project_skills -v`

Ожидается: FAIL, потому что вложенная команда отсутствует.

- [ ] **Шаг 3: Добавить parser и dispatch**

Создать вложенные parsers внутри `project`:

```python
project_skills = project.add_parser(
    "skills", help="Управлять Git-источником skills logical project"
).add_subparsers(dest="project_skills_command", required=True)
use_branch = project_skills.add_parser("use-branch", help="Выбрать удалённую ветку локально")
use_branch.add_argument("branch")
project_skills.add_parser("use-main", help="Вернуться к default branch")
project_skills.add_parser("status", help="Показать источник и активную ревизию")
```

Определить текущий logical project, создать manager, вывести `json.dumps(status.as_dict(), ensure_ascii=False, indent=2)` и вернуть ненулевой код для небезопасных refs или отсутствующей конфигурации.

- [ ] **Шаг 4: Запустить тесты CLI и сделать commit**

Команда: `pytest tests/test_cli.py -v`

Ожидается: PASS.

```bash
git add src/agent_engineering_kit/cli.py tests/test_cli.py
git commit -m "feat(cli): manage project skills branch"
```

### Задача 7: Изоляция CI и сквозная безопасность

**Файлы:**
- Изменить: `src/agent_engineering_kit/project_skills.py`
- Изменить: `src/agent_engineering_kit/validation.py`
- Изменить: `src/agent_engineering_kit/cli.py`
- Изменить: `tests/test_project_skills.py`
- Изменить: `tests/test_repository.py`

**Интерфейсы:**
- Использует: `requested_branch(ci=True)` и существующий путь `validate(repository, paths, "all", include_local=False)`.
- Предоставляет: воспроизводимую диагностику CI с default branch и разрешённым SHA без чтения machine-local override.

- [ ] **Шаг 1: Написать падающие тесты CI и маскирования секретов**

```python
def test_ci_validation_ignores_machine_branch_override(project_fixture, monkeypatch):
    manager = project_fixture.manager(validator=lambda _: (True, []))
    manager.set_branch("feat/local-only")
    observed = manager.inspect(ci=True)
    assert observed["requested_branch"] == "main"
    assert observed["local_override_applied"] is False


def test_status_masks_credential_bearing_runtime_remote(project_fixture):
    project_fixture.rewrite_runtime_origin("https://user:secret@example.com/project-skills.git")
    rendered = json.dumps(project_fixture.manager().status().as_dict())
    assert "secret" not in rendered
```

- [ ] **Шаг 2: Подтвердить падение тестов CI**

Команда: `pytest tests/test_project_skills.py -k 'ci_validation or masks' -v`

Ожидается: FAIL до подключения CI inspection и полного маскирования.

- [ ] **Шаг 3: Добавить validator project-skills**

Зарегистрировать validator, который не выполняет Git-записей во время `validate --ci`: он проверяет manifest и сообщает active/default состояние источника. Если immutable revision уже активна, включить её в диагностику. Validator не должен загружать local branch override или объявлять непроверенный remote commit успешно проверенным.

- [ ] **Шаг 4: Запустить проверку repository и полный целевой набор тестов**

Команды:

```bash
pytest tests/test_project_skills.py tests/test_projects.py tests/test_clients.py tests/test_resync.py tests/test_cli.py tests/test_repository.py -v
agent-kit validate --ci
```

Ожидается: PASS; вывод CI сообщает, что user-local inputs отключены.

- [ ] **Шаг 5: Сделать commit**

```bash
git add src/agent_engineering_kit/project_skills.py src/agent_engineering_kit/validation.py src/agent_engineering_kit/cli.py tests/test_project_skills.py tests/test_repository.py
git commit -m "test(skills): enforce project skills isolation"
```

### Задача 8: Русская пользовательская документация, версия и финальная проверка

**Файлы:**
- Изменить: `README.md`
- Изменить: `docs/INDEX.md`
- Изменить: `templates/project/project.yaml`
- Изменить: `app.version`
- Изменить: `src/agent_engineering_kit/__init__.py`
- Проверить: `tests/test_documentation.py`
- Проверить: `tests/test_repository.py`

**Интерфейсы:**
- Использует: реализованные CLI и контракт manifest.
- Предоставляет: полное русское руководство по установке и эксплуатации и release-версию `0.10.0`.

- [ ] **Шаг 1: Добавить приёмочные проверки документации**

Расширить тесты документации и потребовать следующие буквальные примеры команд:

```python
required = (
    "agent-kit project skills use-branch",
    "agent-kit project skills use-main",
    "agent-kit project skills status",
    "agent-kit resync",
)
readme = (repository / "README.md").read_text(encoding="utf-8")
assert all(command in readme for command in required)
```

- [ ] **Шаг 2: Подтвердить падение тестов документации**

Команда: `pytest tests/test_documentation.py -v`

Ожидается: FAIL, потому что эксплуатационное руководство ещё не добавлено.

- [ ] **Шаг 3: Написать русское эксплуатационное руководство**

Описать:

1. создание обычного репозитория `project-skills` и структуру `skills/<id>/SKILL.md`;
2. прокомментированный фрагмент `.ai-team/project.yaml`;
3. обновление default `main` через `resync`;
4. проверку ветки PR/MR через `use-branch`, просмотр status и очистку через `use-main`;
5. поведение независимых repositories с общим `project.id`;
6. Git-аутентификацию через SSH agent или credential helper;
7. диагностику `ACTIVE`, `STALE`, `UPDATE_REJECTED`, `NOT_CONFIGURED`;
8. гарантии last-known-good и отклонения небезопасного candidate;
9. явное утверждение, что Kit никогда не делает commit, push, merge и не копирует project skills.

Добавить ссылку на план в `docs/INDEX.md`. Сохранить всю Markdown-прозу человекочитаемой русской, а описания в примерах skill frontmatter — английскими.

- [ ] **Шаг 4: Установить release-версию**

Записать `0.10.0` в `app.version` и `__version__ = "0.10.0"` в `src/agent_engineering_kit/__init__.py`.

- [ ] **Шаг 5: Выполнить финальную проверку**

Команды:

```bash
git diff --check
pytest -q
agent-kit validate --ci
agent-kit help project skills
```

Ожидается: все тесты проходят, результат validation равен `OK`, а help перечисляет `use-branch`, `use-main` и `status`. Если три installed-wheel теста падают только из-за отсутствия `hatchling` в окружении разработчика, установить объявленный `dev` extra в изолированное окружение и повторить полную команду тестов; не ослаблять и не пропускать эти тесты в отслеживаемой конфигурации.

- [ ] **Шаг 6: Сделать commit**

```bash
git add README.md docs/INDEX.md templates/project/project.yaml app.version src/agent_engineering_kit/__init__.py tests/test_documentation.py tests/test_repository.py
git commit -m "docs(skills): document project skills workflow"
```

- [ ] **Шаг 7: Проверить полную ветку**

Сравнить с `main`, подтвердить соответствие каждого раздела спецификации проходящему тесту, проверить отсутствие remote с credentials в tracked-файлах и запросить code review до создания Pull Request.
