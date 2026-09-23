# План реализации управления overrides

> **Для AI-исполнителей:** при реализации плана по задачам обязательно использовать `superpowers:subagent-driven-development` (рекомендуется) или `superpowers:executing-plans`. Выполнение отмечать флажками (`- [ ]`).
> Маркер `Task N` в заголовках нужен утилите извлечения заданий SDD; после него всегда приведено русское название задачи.

**Цель:** Добавить полностью управляемые пользователем ACL и overrides для MCP и skills, симметричный CLI, готовые локальные примеры и подробную русскую документацию.

**Архитектура:** YAML в `<data>/overrides/` остаётся единственным источником истины. Новый модуль `access.py` вычисляет доступ по глобальному и проектному `access.yaml`, существующий механизм применяет определения overrides, а отдельный `override_service.py` атомарно редактирует те же файлы для CLI. Менеджеры MCP и внешних skills вместе с синхронизацией клиентов используют единое итоговое решение.

**Стек технологий:** Python 3.10+, argparse, PyYAML, jsonschema, pytest, Markdown, YAML.

**Спецификация:** `docs/superpowers/specs/2026-09-23-override-controls-design.md`

## Общие ограничения

- Пользователь может отключить любой MCP или skill, включая `required`, `locked` и `enforced`.
- YAML является единственным источником истины; скрытая база настроек запрещена.
- Изменяющие CLI-команды требуют явный `--scope global|project`.
- Глобальный запрет имеет приоритет над проектным разрешением.
- Секреты задаются только ссылками `env:VARIABLE`.
- Пользовательские файлы не перезаписываются и не удаляются без резервной копии.
- Поддерживаются macOS, Linux и Windows.
- Пользовательские сообщения, комментарии и документация пишутся профессиональным русским языком.
- Версия результата — `0.3.0`.

---

## Карта изменяемых файлов

- `src/agent_engineering_kit/access.py` — загрузка, объединение и изменение allow/block.
- `src/agent_engineering_kit/override_service.py` — scope, копирование локальных sources, backup и reset.
- `src/agent_engineering_kit/overrides.py` — per-target `extend`, `replace`, `disable` и относительные пути.
- `src/agent_engineering_kit/mcp_manager.py` — доступный каталог, итоговый desired state и причины отключения.
- `src/agent_engineering_kit/external_skills.py` — полный каталог skills и применение ACL.
- `src/agent_engineering_kit/clients.py` — публикация только итоговых skills и MCP.
- `src/agent_engineering_kit/cli.py` — команды `available`, `enable`, `disable`, `override`, `reset`.
- `src/agent_engineering_kit/resync.py` — инициализация локального workspace overrides.
- `schemas/access.schema.json` — формат `access.yaml`.
- `schemas/override.schema.json` — переносимый путь к source и текущие режимы.
- `skills/first-party/greeting/SKILL.md` — базовый демонстрационный skill.
- `templates/overrides/` — нейтральная конфигурация и готовые примеры.
- `tests/test_access.py` — семантика ACL.
- `tests/test_override_service.py` — безопасное изменение файлов.
- `tests/test_overrides.py` — обратная совместимость per-target overrides.
- `tests/test_mcp_manager.py` и `tests/test_external_skills.py` — интеграция resolver.
- `tests/test_cli.py` — контракт CLI.
- `tests/test_repository.py` — качество YAML и Markdown.
- `README.md`, `AI.md`, `docs/INDEX.md`, `docs/adr/0007-local-overrides.md` — эксплуатационная документация.

---

### Task 1 — задача 1: модель доступа и JSON Schema

**Файлы:**
- Создать: `src/agent_engineering_kit/access.py`
- Создать: `schemas/access.schema.json`
- Создать: `tests/test_access.py`
- Изменить: `src/agent_engineering_kit/validation.py`

**Интерфейсы:**
- Создаёт: `AccessDecision(identifier: str, enabled: bool, reason: str)`.
- Создаёт: `resolve_access(identifiers: set[str], override_root: Path, kind: str, project_id: str | None = None) -> dict[str, AccessDecision]`.
- Создаёт: `validate_access(identifiers_by_kind: dict[str, set[str]], override_root: Path, project_id: str | None = None) -> ValidationResult`.
- Использует: `load_yaml`, `validate_instance`, `ValidationResult`, `AgentKitError`.

- [ ] **Шаг 1. Написать падающие тесты для нейтральной политики, allow, block и приоритета слоёв**

```python
def test_empty_policy_allows_every_known_component(tmp_path: Path) -> None:
    write_yaml(tmp_path / "global/access.yaml", {"version": 1, "mcp": {"allow": [], "block": []}})
    decisions = resolve_access({"context7", "github"}, tmp_path, "mcp")
    assert {key for key, value in decisions.items() if value.enabled} == {"context7", "github"}


def test_block_wins_and_project_cannot_restore_global_block(tmp_path: Path) -> None:
    write_yaml(tmp_path / "global/access.yaml", {"version": 1, "mcp": {"allow": [], "block": ["context7"]}})
    write_yaml(tmp_path / "projects/demo/access.yaml", {"version": 1, "mcp": {"allow": ["context7"], "block": []}})
    decision = resolve_access({"context7"}, tmp_path, "mcp", "demo")["context7"]
    assert decision.enabled is False
    assert decision.reason == "blocked:global"


def test_non_empty_allowlists_are_intersected(tmp_path: Path) -> None:
    write_yaml(tmp_path / "global/access.yaml", {"version": 1, "skills": {"allow": ["greeting", "verification"], "block": []}})
    write_yaml(tmp_path / "projects/demo/access.yaml", {"version": 1, "skills": {"allow": ["greeting"], "block": []}})
    decisions = resolve_access({"greeting", "verification"}, tmp_path, "skills", "demo")
    assert decisions["greeting"].enabled is True
    assert decisions["verification"].reason == "not-allowed:project"
```

- [ ] **Шаг 2. Запустить тесты и подтвердить RED**

Команда: `.venv/bin/python -m pytest tests/test_access.py -q`

Ожидается: сбор тестов завершается ошибкой, поскольку `agent_engineering_kit.access` ещё не существует.

- [ ] **Шаг 3. Реализовать неизменяемую модель доступа**

```python
@dataclass(frozen=True)
class AccessDecision:
    identifier: str
    enabled: bool
    reason: str


def resolve_access(
    identifiers: set[str],
    override_root: Path,
    kind: str,
    project_id: str | None = None,
) -> dict[str, AccessDecision]:
    layers = [("global", override_root / "global/access.yaml")]
    if project_id:
        layers.append(("project", override_root / "projects" / project_id / "access.yaml"))
    decisions = {identifier: AccessDecision(identifier, True, "allowed:catalog") for identifier in identifiers}
    for layer, path in layers:
        if not path.is_file():
            continue
        section = load_yaml(path).get(kind, {})
        allow = set(section.get("allow", []))
        block = set(section.get("block", []))
        for identifier, current in list(decisions.items()):
            if not current.enabled:
                continue
            if identifier in block:
                decisions[identifier] = AccessDecision(identifier, False, f"blocked:{layer}")
            elif allow and identifier not in allow:
                decisions[identifier] = AccessDecision(identifier, False, f"not-allowed:{layer}")
    return decisions
```

Добавить `schemas/access.schema.json` с `version: 1`, необязательными разделами `mcp` и `skills`, уникальными строковыми массивами `allow` и `block`, а также `additionalProperties: false` на каждом уровне объектов.

- [ ] **Шаг 4. Добавить негативные тесты валидации**

```python
def test_unknown_and_conflicting_ids_fail_validation(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "global/access.yaml",
        {"version": 1, "mcp": {"allow": ["missing", "github"], "block": ["github"]}},
    )
    result = validate_access({"mcp": {"github"}, "skills": set()}, tmp_path)
    messages = "\n".join(item.message for item in result.diagnostics)
    assert not result.ok
    assert "неизвестные ID" in messages
    assert "одновременно" in messages
```

- [ ] **Шаг 5. Подключить валидацию и подтвердить GREEN**

Вызывать `validate_access` из существующего валидатора локальных overrides после получения полных наборов ID для MCP и skills. Выполнить:

```bash
.venv/bin/python -m pytest tests/test_access.py tests/test_overrides.py -q
.venv/bin/agent-kit validate overrides
```

Ожидается: все тесты проходят, а валидатор выводит `Результат: OK`.

- [ ] **Шаг 6. Создать коммит**

```bash
git add schemas/access.schema.json src/agent_engineering_kit/access.py src/agent_engineering_kit/validation.py src/agent_engineering_kit/overrides.py tests/test_access.py tests/test_overrides.py
git commit -m "feat(overrides): add access policy resolution"
```

---

### Task 2 — задача 2: применение ACL к MCP и skills

**Файлы:**
- Изменить: `src/agent_engineering_kit/overrides.py`
- Изменить: `src/agent_engineering_kit/mcp_manager.py`
- Изменить: `src/agent_engineering_kit/external_skills.py`
- Изменить: `src/agent_engineering_kit/clients.py`
- Изменить: `src/agent_engineering_kit/explain.py`
- Изменить: `tests/test_overrides.py`
- Изменить: `tests/test_mcp_manager.py`
- Изменить: `tests/test_external_skills.py`
- Изменить: `tests/test_clients.py`

**Интерфейсы:**
- Использует: `resolve_access(...) -> dict[str, AccessDecision]` из задачи 1.
- Создаёт: `McpManager.available(project: LogicalProject | None = None) -> list[dict[str, Any]]`.
- Создаёт: `ExternalSkillManager.available() -> list[dict[str, Any]]`.
- Сохраняет: существующие методы `desired()` возвращают только включённые компоненты.

- [ ] **Шаг 1. Написать падающие тесты на отключение ранее защищённых компонентов**

```python
def test_access_policy_can_disable_required_mcp(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    write_yaml(paths.overrides / "global/access.yaml", {"version": 1, "mcp": {"allow": [], "block": ["context7"]}})
    rows = McpManager(repository, paths).available()
    context7 = next(row for row in rows if row["id"] == "context7")
    assert context7["enabled"] is False
    assert context7["access_reason"] == "blocked:global"


def test_access_policy_can_disable_enforced_skill(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    write_yaml(paths.overrides / "global/access.yaml", {"version": 1, "skills": {"allow": [], "block": ["verification"]}})
    rows = ExternalSkillManager(repository, paths).available()
    assert next(row for row in rows if row["id"] == "verification")["enabled"] is False
```

- [ ] **Шаг 2. Запустить целевые тесты и подтвердить RED**

Команда:

```bash
.venv/bin/python -m pytest tests/test_mcp_manager.py tests/test_external_skills.py -q
```

Ожидается: тесты падают, потому что `available` и фильтрация ACL ещё не реализованы.

- [ ] **Шаг 3. Удалить только локальный запрет на отключение**

Изменить `apply_local_overrides`: режим `mode: disable` должен удалять любую цель независимо от `enforced`. В `validate_overrides` разрешить `disable` для защищённых элементов, сохранив прежние ограничения для `replace` и изменений `ENFORCED_FIELDS`.

- [ ] **Шаг 4. Реализовать полное представление каталога и фильтрацию желаемого состояния**

Для каждого менеджера:

1. load the full catalog;
2. apply field overrides;
3. calculate `resolve_access` for every ID;
4. mark legacy `mode: disable` as `disabled:override`;
5. return all IDs from `available` with `enabled` and `access_reason`;
6. filter disabled IDs in `desired` before install or registration.

Ensure `McpManager.list` and `ExternalSkillManager.list` retain their public shape but do not lose disabled rows; use status `DISABLED` for explicit user choice and `inactive` only for unmatched activation signals.

- [ ] **Шаг 5. Проверить публикацию в клиенты и вывод explain**

```python
def test_disabled_skill_is_removed_from_shared_discovery(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    write_yaml(paths.overrides / "global/access.yaml", {"version": 1, "skills": {"allow": [], "block": ["verification"]}})
    sync_clients(repository, paths)
    assert not (paths.installations / "clients/shared/skills/verification").exists()
```

Добавить проверки, что `config explain` показывает слой политики и причину отключения MCP и skills.

- [ ] **Шаг 6. Запустить регрессионные тесты**

```bash
.venv/bin/python -m pytest tests/test_overrides.py tests/test_mcp_manager.py tests/test_external_skills.py tests/test_clients.py -q
```

Ожидается: все тесты проходят.

- [ ] **Шаг 7. Создать коммит**

```bash
git add src/agent_engineering_kit/overrides.py src/agent_engineering_kit/mcp_manager.py src/agent_engineering_kit/external_skills.py src/agent_engineering_kit/clients.py src/agent_engineering_kit/explain.py tests/test_overrides.py tests/test_mcp_manager.py tests/test_external_skills.py tests/test_clients.py
git commit -m "feat(overrides): apply access policy to mcp and skills"
```

---

### Task 3 — задача 3: сервис безопасного изменения overrides

**Файлы:**
- Создать: `src/agent_engineering_kit/override_service.py`
- Создать: `tests/test_override_service.py`
- Изменить: `src/agent_engineering_kit/overrides.py`

**Интерфейсы:**
- Создаёт: `OverrideScope(kind: Literal["global", "project"], root: Path, project_id: str | None)`.
- Создаёт: `resolve_scope(paths: KitPaths, scope: str, cwd: Path) -> OverrideScope`.
- Создаёт: `set_component_access(..., enabled: bool) -> Path`.
- Создаёт: `install_skill_override(..., source: Path) -> Path`.
- Создаёт: `install_mcp_override(..., source: Path) -> Path`.
- Создаёт: `reset_component_override(...) -> list[Path]`.

- [ ] **Шаг 1. Написать падающие тесты атомарного изменения ACL**

```python
def test_disable_and_enable_edit_the_same_yaml_source(tmp_path: Path) -> None:
    scope = OverrideScope("global", tmp_path / "global", None)
    path = set_component_access(scope, "mcp", "context7", enabled=False)
    assert load_yaml(path)["mcp"]["block"] == ["context7"]
    set_component_access(scope, "mcp", "context7", enabled=True)
    assert load_yaml(path)["mcp"]["block"] == []


def test_project_scope_requires_logical_project(tmp_path: Path) -> None:
    with pytest.raises(AgentKitError, match="Логический проект не найден"):
        resolve_scope(paths_fixture(tmp_path), "project", tmp_path)
```

- [ ] **Шаг 2. Запустить тесты и подтвердить RED**

Команда: `.venv/bin/python -m pytest tests/test_override_service.py -q`

Ожидается: ошибка импорта нового сервиса.

- [ ] **Шаг 3. Реализовать выбор области и изменение доступа**

Использовать `atomic_write` и детерминированно отсортированные массивы. Сохранять не относящиеся к операции разделы `mcp` и `skills`. Проверять итоговый документ до замены исходного файла.

- [ ] **Шаг 4. Добавить тесты источника skill и относительных путей**

```python
def test_skill_override_is_copied_and_uses_relative_path(tmp_path: Path) -> None:
    source = tmp_path / "custom"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nversion: 1\nname: greeting\ndescription: Пример\n"
        "policy: configurable\nrequires:\n  model_capabilities: [reasoning]\n---\n# Приветствие\n",
        encoding="utf-8",
    )
    scope = OverrideScope("global", tmp_path / "global", None)
    target = install_skill_override(scope, "greeting", source)
    document = load_yaml(target)
    assert document["override"]["mode"] == "replace"
    relative = document["override"]["value"]["path"]
    assert (target.parent / relative).resolve().is_dir()
```

Обновить разрешение отдельных целей: `value.path` должен вычисляться относительно объявляющего его YAML, а не рабочего каталога процесса.

- [ ] **Шаг 5. Добавить тесты секретов MCP и резервных копий**

```python
def test_mcp_override_rejects_literal_secret(tmp_path: Path) -> None:
    source = write_yaml(tmp_path / "mcp.yaml", {"mode": "extend", "value": {"environment": {"TOKEN": "literal-value"}}})
    with pytest.raises(AgentKitError, match="env:VARIABLE"):
        install_mcp_override(OverrideScope("global", tmp_path / "global", None), "github", source)


def test_reset_moves_override_to_timestamped_backup(tmp_path: Path) -> None:
    scope = OverrideScope("global", tmp_path / "global", None)
    active = scope.root / "skills/greeting.yaml"
    write_yaml(active, {"target": "greeting", "override": {"mode": "disable"}})
    moved = reset_component_override(scope, "skills", "greeting", tmp_path / "backups")
    assert not active.exists()
    assert any(path.name == "greeting.yaml" and path.exists() for path in moved)
```

- [ ] **Шаг 6. Запустить тесты сервиса и overrides**

```bash
.venv/bin/python -m pytest tests/test_override_service.py tests/test_overrides.py -q
```

Ожидается: все тесты проходят.

- [ ] **Шаг 7. Создать коммит**

```bash
git add src/agent_engineering_kit/override_service.py src/agent_engineering_kit/overrides.py tests/test_override_service.py tests/test_overrides.py
git commit -m "feat(overrides): add safe override editing service"
```

---

### Task 4 — задача 4: симметричные CLI-команды

**Файлы:**
- Изменить: `src/agent_engineering_kit/cli.py`
- Создать: `tests/test_cli.py`

**Интерфейсы:**
- Использует: `McpManager.available`, `ExternalSkillManager.available` из задачи 2.
- Использует: все функции изменения из `override_service.py` из задачи 3.
- Сохраняет: существующие команды `list`, `status`, `explain` и `rollback`.

- [ ] **Шаг 1. Написать контрактные тесты парсера**

```python
@pytest.mark.parametrize("resource", ["skills", "mcp"])
@pytest.mark.parametrize("action", ["enable", "disable", "reset"])
def test_mutating_commands_require_explicit_scope(resource: str, action: str) -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args([resource, action, "greeting"])


def test_available_does_not_require_scope() -> None:
    args = _parser().parse_args(["skills", "available"])
    assert args.skills_command == "available"
```

Предоставить `_parser().parse_args` через небольшой тестовый помощник либо тестировать `_parser` напрямую; для проверки только парсера не запускать отдельный процесс оболочки.

- [ ] **Шаг 2. Запустить тесты парсера и подтвердить RED**

Команда: `.venv/bin/python -m pytest tests/test_cli.py -q`

Ожидается: парсер отклоняет неизвестные подкоманды.

- [ ] **Шаг 3. Добавить симметричные подпарсеры**

Для обоих типов ресурсов добавить `available`, `enable`, `disable`, `override`, `reset`. Изменяющие команды требуют:

```python
command.add_argument("id")
command.add_argument("--scope", choices=["global", "project"], required=True)
command.add_argument("--resync", action="store_true")
```

Для `override` дополнительно требуется `--from` с назначением `source`.

- [ ] **Шаг 4. Добавить тесты поведения CLI с изолированным каталогом данных**

```python
def test_cli_disable_then_enable_round_trip(monkeypatch, tmp_path: Path, capsys) -> None:
    repository = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("AGENT_KIT_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("AGENT_KIT_REPOSITORY", str(repository))
    assert run(["mcp", "disable", "context7", "--scope", "global"]) == 0
    assert "context7" in load_yaml(tmp_path / "overrides/global/access.yaml")["mcp"]["block"]
    assert run(["mcp", "enable", "context7", "--scope", "global"]) == 0
    assert "context7" not in load_yaml(tmp_path / "overrides/global/access.yaml")["mcp"]["block"]
```

Добавить аналогичные случаи для skill, override, reset, неизвестного ID и проекта без манифеста.

- [ ] **Шаг 5. Реализовать маршрутизацию команд и необязательный resync**

После успешного изменения выводить точный изменённый путь и итоговое решение. При наличии `--resync` вызывать существующий `resync` только после успешной атомарной записи.

- [ ] **Шаг 6. Запустить регрессионные тесты CLI и менеджеров**

```bash
.venv/bin/python -m pytest tests/test_cli.py tests/test_mcp_manager.py tests/test_external_skills.py -q
```

Ожидается: все тесты проходят.

- [ ] **Шаг 7. Создать коммит**

```bash
git add src/agent_engineering_kit/cli.py tests/test_cli.py
git commit -m "feat(cli): add mcp and skill override commands"
```

---

### Task 5 — задача 5: greeting и установочные примеры

**Файлы:**
- Создать: `skills/first-party/greeting/SKILL.md`
- Создать: `templates/overrides/README.md`
- Создать: `templates/overrides/global/access.yaml`
- Создать: `templates/overrides/global/mcp/github.yaml.example`
- Создать: `templates/overrides/global/skills/greeting.yaml.example`
- Создать: `templates/overrides/projects/README.md`
- Создать: `templates/overrides/examples/access.yaml`
- Создать: `templates/overrides/examples/greeting/SKILL.md`
- Создать: `templates/overrides/examples/greeting/scripts/greet.py`
- Изменить: `src/agent_engineering_kit/override_service.py`
- Изменить: `src/agent_engineering_kit/resync.py`
- Создать: `tests/test_override_templates.py`
- Создать: `tests/test_resync.py`

**Интерфейсы:**
- Создаёт: `initialize_override_workspace(repository: Path, paths: KitPaths) -> list[Path]`.
- Использует: `KitPaths.overrides`, `atomic_write` и каталог репозитория `templates/overrides`.

- [ ] **Шаг 1. Написать падающие тесты идемпотентности**

```python
def test_initializer_creates_neutral_policy_and_examples(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    paths = KitPaths(repository, tmp_path, tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")
    created = initialize_override_workspace(repository, paths)
    assert paths.overrides / "global/access.yaml" in created
    assert (paths.overrides / "examples/greeting/SKILL.md").is_file()


def test_initializer_never_overwrites_user_policy(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    paths = KitPaths(repository, tmp_path, tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")
    target = paths.overrides / "global/access.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("user-owned\n", encoding="utf-8")
    initialize_override_workspace(repository, paths)
    assert target.read_text(encoding="utf-8") == "user-owned\n"
```

- [ ] **Шаг 2. Запустить тесты и подтвердить RED**

Команда: `.venv/bin/python -m pytest tests/test_override_templates.py -q`

Ожидается: инициализатор ещё отсутствует.

- [ ] **Шаг 3. Добавить базовый skill greeting**

Создать корректный first-party `SKILL.md` с `name: greeting`, настраиваемой политикой и инструкцией отвечать точно `Привет!`, если локальная реализация его не заменила.

- [ ] **Шаг 4. Добавить динамический пример**

Пример `SKILL.md` предписывает агенту запускать `scripts/greet.py`. Содержимое скрипта:

```python
from __future__ import annotations

import getpass


def main() -> None:
    print(f"Привет, {getpass.getuser()}!")


if __name__ == "__main__":
    main()
```

Добавить модульный тест, который подменяет `getpass.getuser`, возвращает `developer` и проверяет строку `Привет, developer!`.

- [ ] **Шаг 5. Реализовать инициализацию с копированием только отсутствующих файлов**

Обходить `templates/overrides` в детерминированном порядке. Создавать каталоги и копировать файл только при отсутствии назначения. Возвращать только вновь созданные пути. Вызывать функцию из `resync` сразу после `ensure_runtime` и до валидации локальных overrides.

- [ ] **Шаг 6. Запустить тесты шаблонов, skill и resync**

```bash
.venv/bin/python -m pytest tests/test_override_templates.py tests/test_repository.py tests/test_resync.py -q
```

Ожидается: все тесты проходят, а повторная инициализация не сообщает о созданных файлах.

- [ ] **Шаг 7. Создать коммит**

```bash
git add skills/first-party/greeting templates/overrides src/agent_engineering_kit/override_service.py src/agent_engineering_kit/resync.py tests/test_override_templates.py tests/test_repository.py tests/test_resync.py
git commit -m "feat(overrides): add greeting and local examples"
```

---

### Task 6 — задача 6: русская локализация, YAML-комментарии и карта репозитория

**Файлы:**
- Изменить: `README.md`
- Изменить: `AI.md`
- Изменить: `docs/INDEX.md`
- Изменить: `docs/adr/0007-local-overrides.md`
- Изменить: все отслеживаемые `*.yaml` и `*.yml`
- Изменить: затронутые строки документации Python и пользовательские диагностические сообщения в `src/agent_engineering_kit/`
- Изменить: `tests/test_repository.py`

**Интерфейсы:**
- Документирует все публичные команды и карту каталогов.
- Сохраняет технические идентификаторы, названия продуктов и API, а также синтаксис команд без перевода.

- [ ] **Шаг 1. Усилить тест документации YAML и подтвердить RED**

Заменить проверку только начального комментария контрактом: нетривиальный YAML должен содержать не менее двух содержательных строк комментариев и комментарий перед первым элементом повторяющейся последовательности:

```python
comments = [line for line in lines if line.lstrip().startswith("#") and len(line.lstrip(" #")) >= 20]
assert len(comments) >= 2, name
first_sequence = next((index for index, line in enumerate(lines) if line.lstrip().startswith("- ")), None)
if first_sequence is not None:
    assert any(line.lstrip().startswith("#") for line in lines[: first_sequence + 1]), name
```

Запустить `.venv/bin/python -m pytest tests/test_repository.py::test_all_tracked_yaml_files_have_explanatory_comments -q` и убедиться, что недостаточно документированные файлы не проходят проверку.

- [ ] **Шаг 2. Переписать комментарии YAML**

Во всех отслеживаемых YAML/YML добавить краткие русские комментарии о назначении, основных разделах, неочевидных значениях и первом элементе повторяющихся структур. Не переводить ID, команды, URL, имена переменных окружения и значения перечислений.

- [ ] **Шаг 3. Проверить комментарии в исходниках и диагностические сообщения**

Найти пользовательский текст командой:

```bash
rg -n '\b(support|desired state|effective|override|runtime|repository|validation|candidate|findings)\b' src README.md AI.md docs rules security skills
```

Переписать неестественный смешанный текст, сохранив машинные идентификаторы в кодовых фрагментах и полях вывода команд.

- [ ] **Шаг 4. Добавить в README карту репозитория**

Описать каждый каталог верхнего уровня в таблице со столбцами:

```text
Путь | Ответственность | Связи | Переиспользование
```

Добавить полные примеры ручного YAML и всех CLI-команд. Объяснить приоритеты global/project, неограниченное отключение, разницу между `inactive` и `disabled`, резервные копии и полный сценарий greeting.

- [ ] **Шаг 5. Обновить каноническую документацию**

Обновить `AI.md`, ADR 0007 и `docs/INDEX.md`, чтобы иерархия источников истины, политика доступа и команды совпадали с README и принятой спецификацией.

- [ ] **Шаг 6. Запустить проверки документации**

```bash
.venv/bin/python -m pytest tests/test_repository.py -q
.venv/bin/agent-kit validate schemas
git diff --check
```

Ожидается: все проверки проходят, нерабочих относительных ссылок нет.

- [ ] **Шаг 7. Создать коммит**

```bash
git add README.md AI.md docs rules security skills src tests/test_repository.py .github .pre-commit-config.yaml catalog clients locks mcp models templates
git commit -m "docs(agent-kit): document overrides and repository structure"
```

---

### Task 7 — задача 7: полная проверка и независимый review

**Файлы:**
- Изменять только файлы, необходимые для устранения подтверждённых замечаний review.

**Интерфейсы:**
- Проверяет каждый критерий приёмки из спецификации.

- [ ] **Шаг 1. Запустить полный набор автоматических проверок**

```bash
.venv/bin/python -m pytest -q
.venv/bin/agent-kit validate --ci
.venv/bin/python -m compileall -q src tests
for script in bootstrap/*.sh; do bash -n "$script"; done
git diff --check
```

Ожидается: ни одной ошибки и вывод `Результат: OK`.

- [ ] **Шаг 2. Выполнить приёмочные сценарии CLI в изолированном каталоге данных**

Проверить, не затрагивая настоящие пользовательские overrides:

```bash
KIT_ACCEPTANCE_DATA=$(mktemp -d)
AGENT_KIT_DATA_HOME="$KIT_ACCEPTANCE_DATA" .venv/bin/agent-kit install
AGENT_KIT_DATA_HOME="$KIT_ACCEPTANCE_DATA" .venv/bin/agent-kit skills available
AGENT_KIT_DATA_HOME="$KIT_ACCEPTANCE_DATA" .venv/bin/agent-kit mcp disable context7 --scope global
AGENT_KIT_DATA_HOME="$KIT_ACCEPTANCE_DATA" .venv/bin/agent-kit mcp enable context7 --scope global
AGENT_KIT_DATA_HOME="$KIT_ACCEPTANCE_DATA" .venv/bin/agent-kit skills override greeting --from "$KIT_ACCEPTANCE_DATA/overrides/examples/greeting" --scope global
AGENT_KIT_DATA_HOME="$KIT_ACCEPTANCE_DATA" .venv/bin/agent-kit skills reset greeting --scope global
```

Подтвердить создание файлов, итоговые состояния, восстановление из резервной копии и отсутствие секретов в открытом виде.

- [ ] **Шаг 3. Запросить review кода в режиме только для чтения**

Передать проверяющему принятую спецификацию, этот план, базовый коммит `16ff9be`, текущий HEAD и точные результаты проверок. Потребовать классификацию замечаний P0/P1/P2 со ссылками на файлы и строки.

- [ ] **Шаг 4. Устранить замечания review через тесты RED–GREEN**

Каждое замечание P0/P1/P2 воспроизвести падающим тестом, внести минимальное исправление, затем повторить целевой тест и полный набор проверок. Повторять review до полного отсутствия P0/P1/P2.

- [ ] **Шаг 5. Создать итоговый коммит, если review потребовал исправлений**

```bash
git status --short
git add -A
git commit -m "fix(overrides): address integration review findings"
```

- [ ] **Шаг 6. Проверить итоговое состояние ветки**

```bash
git status --short
git log --oneline 16ff9be..HEAD
cat app.version
.venv/bin/python -c 'import agent_engineering_kit; print(agent_engineering_kit.__version__)'
```

Ожидается: чистое рабочее дерево, версия `0.3.0` и только Conventional Commits в ветке `feat/23-09-2026-add-override-controls`.
