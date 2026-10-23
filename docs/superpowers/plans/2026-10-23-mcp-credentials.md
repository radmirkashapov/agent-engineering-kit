# MCP Credentials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать безопасный импорт локальных credentials, передачу только объявленных переменных stdio MCP через управляемый launcher и диагностику без раскрытия значений.

**Architecture:** Новый модуль `mcp_credentials` владеет строгим разбором, allowlist и machine-local vault, а `mcp_launcher` — неизменяемым launch contract и окружением дочернего MCP-процесса. `register_native_mcp` регистрирует launcher только для stdio MCP с `environment`; remote OAuth остаётся нативным состоянием каждого клиента.

**Tech Stack:** Python 3.10+, стандартная библиотека (`argparse`, `dataclasses`, `json`, `os`, `pathlib`, `tempfile`), PyYAML, pytest, существующие `KitPaths`, `McpManager`, native client adapters и validation framework.

**Spec:** `docs/superpowers/specs/2026-10-23-mcp-credentials-design.md`

## Global Constraints

- Секреты допускаются только через переменные окружения или внешнее хранилище секретов.
- Значения не попадают в Git, generated client config, effective policy, state, журналы, исключения и диагностические отчёты.
- Канонический vault: `<data>/secrets/mcp-creds.env`; на POSIX каталог имеет режим `0700`, файл — `0600`.
- Импорт принимает только имена из effective MCP definitions и не исполняет shell-синтаксис.
- `mcp-creds.example.env` отслеживается Git, `mcp-creds.env` и `mcp-creds.*.env` игнорируются.
- Vault имеет приоритет только для объявленных непустых значений; унаследованное окружение сохраняет обратную совместимость.
- Remote OAuth credentials принадлежат каждому клиенту; Kit их не читает, не переносит и не экспортирует.
- Codex CLI и Claude Code получают managed registrations; Claude Desktop, OpenCode и Cline сохраняют `CONFIG_REQUIRED`.
- `.env.example` сохраняется для обратной совместимости; специализированный MCP-контракт проверяется по `mcp-creds.example.env`.
- Пользовательские неотслеживаемые `.ai/` и `uv.lock` не изменяются.
- После каждого коммита `app.version` и `agent_engineering_kit.__version__` должны совпадать.

---

## Карта файлов

- `src/agent_engineering_kit/mcp_credentials.py` — строгий parser, allowlist, безопасный vault, статусы имён.
- `src/agent_engineering_kit/mcp_launcher.py` — launch contract и запуск stdio MCP с минимальным окружением credentials.
- `src/agent_engineering_kit/paths.py` — путь `<data>/secrets` и создание защищённого каталога.
- `src/agent_engineering_kit/clients.py` — генерация contracts и регистрация launcher в Codex/Claude Code.
- `src/agent_engineering_kit/mcp_manager.py` — activation signals учитывают безопасно импортированные credentials.
- `src/agent_engineering_kit/cli.py` — `mcp creds import|status|clear`.
- `src/agent_engineering_kit/doctor.py` — проверка required credentials без значений.
- `src/agent_engineering_kit/definitions.py` — проверка MCP env references по специализированному шаблону.
- `src/agent_engineering_kit/git_hygiene.py` — запрет tracked/staged локальных credential-файлов.
- `mcp-creds.example.env` — отслеживаемый перечень переменных базовых MCP без значений.
- `.gitignore`, `.env.example` — защита локальных файлов и совместимость.
- `README.md`, `mcp/README.md`, `clients/*/README.md` — импорт, включение MCP, OAuth и runbooks клиентов.
- `tests/test_mcp_credentials.py` — parser, vault, permissions и status.
- `tests/test_mcp_launcher.py` — contract, precedence, process environment и отказ до запуска.
- `tests/test_clients.py`, `tests/test_cli.py`, `tests/test_doctor.py`, `tests/test_git_hygiene.py`, `tests/test_repository.py` — интеграционные контракты.

### Задача 1: Список разрешённых переменных, разбор и хранилище

**Файлы:**
- Создать: `src/agent_engineering_kit/mcp_credentials.py`
- Изменить: `src/agent_engineering_kit/paths.py`
- Создать: `tests/test_mcp_credentials.py`
- Изменить: `app.version`
- Изменить: `src/agent_engineering_kit/__init__.py`

**Интерфейсы:**
- Использует: итоговые записи MCP из `McpManager.available(project, access_profile=...)`; значения `environment` имеют вид `env:VARIABLE`.
- Предоставляет: `CredentialRequirement`, `credential_requirements(servers)`, `parse_credentials(text: str, *, allowed: set[str] | None) -> dict[str, str]` и методы `McpCredentialStore`: `import_file`, `load`, `status`, `clear`.

- [ ] **Шаг 1: Написать падающие тесты разбора и списка разрешённых имён**

```python
def make_paths(tmp_path: Path) -> KitPaths:
    data = tmp_path / "data"
    return KitPaths(tmp_path / "repository", data, data / "runtime", data / "projects", data / "overrides")


def test_requirements_include_environment_references_and_required_names():
    servers = [{
        "id": "github",
        "environment": {"GITHUB_TOKEN": "env:GITHUB_PERSONAL_ACCESS_TOKEN"},
        "required_environment": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    }]
    requirements = credential_requirements(servers)
    assert requirements["GITHUB_PERSONAL_ACCESS_TOKEN"].required_by == ("github",)


def test_parser_treats_input_as_data_and_preserves_equals_in_value():
    assert parse_credentials("TOKEN=a=b=c\n", allowed={"TOKEN"}) == {"TOKEN": "a=b=c"}


@pytest.mark.parametrize("content", [
    "export TOKEN=value\n",
    "TOKEN=$(whoami)\n",
    "TOKEN=${OTHER}\n",
    "TOKEN=`whoami`\n",
    "TOKEN=one\nTOKEN=two\n",
    "UNKNOWN=value\n",
    "BAD-NAME=value\n",
])
def test_parser_rejects_unsafe_or_unknown_input_without_echoing_value(content):
    with pytest.raises(AgentKitError) as raised:
        parse_credentials(content, allowed={"TOKEN"})
    assert "value" not in str(raised.value)
    assert "whoami" not in str(raised.value)
```

- [ ] **Шаг 2: Запустить тесты разбора и подтвердить отсутствие нового модуля**

Команда: `pytest -q tests/test_mcp_credentials.py -k 'requirements or parser'`

Ожидание: сбор тестов падает с `ModuleNotFoundError: agent_engineering_kit.mcp_credentials`.

- [ ] **Шаг 3: Реализовать поиск требований и строгий разбор**

```python
@dataclass(frozen=True)
class CredentialRequirement:
    name: str
    required_by: tuple[str, ...]
    optional_for: tuple[str, ...]


def credential_requirements(servers: Iterable[dict[str, Any]]) -> dict[str, CredentialRequirement]:
    owners: dict[str, dict[str, set[str]]] = {}
    for server in servers:
        identifier = str(server["id"])
        required = {str(name) for name in server.get("required_environment", [])}
        referenced = {
            str(value)[4:]
            for value in server.get("environment", {}).values()
            if str(value).startswith("env:")
        } | required
        for name in referenced:
            bucket = owners.setdefault(name, {"required": set(), "optional": set()})
            bucket["required" if name in required else "optional"].add(identifier)
    return {
        name: CredentialRequirement(
            name=name,
            required_by=tuple(sorted(bucket["required"])),
            optional_for=tuple(sorted(bucket["optional"])),
        )
        for name, bucket in sorted(owners.items())
    }
```

Реализовать `parse_credentials`: делить присваивание по первому `=`, проверять ключ выражением `^[A-Za-z_][A-Za-z0-9_]*$`, отклонять дубликаты и последовательности `` ` ``, `$(` и `${`. Ошибка `AgentKitError` содержит только номер строки и имя переменной.

- [ ] **Шаг 4: Написать падающие тесты хранилища и прав доступа**

```python
def test_import_is_atomic_private_and_status_never_contains_values(tmp_path):
    paths = make_paths(tmp_path)
    source = tmp_path / "mcp-creds.env"
    source.write_text("TOKEN=super-secret\nOPTIONAL=\n", encoding="utf-8")
    servers = [{
        "id": "sample",
        "environment": {"TOKEN": "env:TOKEN", "OPTIONAL": "env:OPTIONAL"},
        "required_environment": ["TOKEN"],
    }]
    store = McpCredentialStore(paths)
    target = store.import_file(source, servers)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    rendered = json.dumps(store.status(servers))
    assert "super-secret" not in rendered
    assert {row["name"]: row["status"] for row in store.status(servers)} == {
        "OPTIONAL": "OPTIONAL",
        "TOKEN": "SET",
    }


def test_clear_removes_only_the_canonical_vault(tmp_path):
    paths = make_paths(tmp_path)
    paths.secrets.mkdir(parents=True)
    paths.secrets.joinpath("mcp-creds.env").write_text("TOKEN=value\n")
    assert McpCredentialStore(paths).clear() is True
    assert not paths.secrets.joinpath("mcp-creds.env").exists()
```

- [ ] **Шаг 5: Запустить тесты хранилища и подтвердить ожидаемое падение**

Команда: `pytest -q tests/test_mcp_credentials.py -k 'import or clear'`

Ожидание: тесты падают, потому что `KitPaths.secrets` и сохранение через `McpCredentialStore` ещё отсутствуют.

- [ ] **Шаг 6: Реализовать безопасные пути и операции хранилища**

Добавить в конец `KitPaths` поле `secrets: Path | None = None`, по умолчанию направить его в `data / "secrets"` и создавать через `ensure_runtime`. На POSIX после создания каталога вызывать `chmod(0o700)`. Метод `McpCredentialStore.import_file` сначала разбирает данные, записывает временный файл в том же каталоге, устанавливает `0600`, выполняет `flush`, `os.fsync` и затем `os.replace`; `load` отклоняет POSIX-файл с правами для группы или остальных пользователей.

```python
class McpCredentialStore:
    def __init__(self, paths: KitPaths):
        self.paths = paths

    @property
    def vault_path(self) -> Path:
        return self.paths.secrets / "mcp-creds.env"

    def import_file(self, source: Path, servers: Iterable[dict[str, Any]]) -> Path:
        requirements = credential_requirements(servers)
        values = parse_credentials(source.read_text(encoding="utf-8"), allowed=set(requirements))
        self._write_private(values)
        self._write_metadata(names=sorted(name for name, value in values.items() if value))
        return self.vault_path

    def load(self) -> dict[str, str]:
        if not self.vault_path.is_file():
            return {}
        self._validate_permissions()
        return parse_credentials(self.vault_path.read_text(encoding="utf-8"), allowed=None)

    def status(self, servers: Iterable[dict[str, Any]]) -> list[dict[str, object]]:
        requirements = credential_requirements(servers)
        values = self.load()
        return [
            {
                "name": name,
                "status": "SET" if values.get(name) else ("MISSING" if requirement.required_by else "OPTIONAL"),
                "required_by": list(requirement.required_by),
                "optional_for": list(requirement.optional_for),
            }
            for name, requirement in requirements.items()
        ]

    def clear(self) -> bool:
        existed = self.vault_path.exists() or self.metadata_path.exists()
        self.vault_path.unlink(missing_ok=True)
        self.metadata_path.unlink(missing_ok=True)
        return existed
```

`parse_credentials(..., allowed=None)` validates the stored format without applying a second allowlist; import is the only write path and already enforces the effective allowlist. `_write_private` implements the atomic `0600` write described above, and `_validate_permissions` rejects group/other POSIX bits. `_write_metadata` atomically writes `<data>/state/mcp-credentials.json` with schema version, UTC `imported_at` and the sorted list of set names; hashes, lengths and values are forbidden. On Windows, the same machine-local path and atomic replacement are used without loosening existing ACLs. Status rows contain only `name`, `status`, `required_by` and `optional_for`. Empty vault values are treated as absent.

Расширить тест хранилища: разобрать `mcp-credentials.json`, проверить точный набор ключей `version`, `imported_at`, `names` и убедиться, что в сериализованных метаданных нет ни `super-secret`, ни длины этого значения.

- [ ] **Шаг 7: Запустить модуль тестов credentials**

Команда: `pytest -q tests/test_mcp_credentials.py`

Ожидание: все тесты проходят.

- [ ] **Шаг 8: Поднять patch-версию и закоммитить самостоятельную реализацию хранилища**

Set both version files to `0.8.6`, then run:

```bash
git add app.version src/agent_engineering_kit/__init__.py src/agent_engineering_kit/paths.py src/agent_engineering_kit/mcp_credentials.py tests/test_mcp_credentials.py
git commit -m "feat(mcp): add secure credential vault"
```

### Задача 2: Контракты запуска stdio MCP

**Файлы:**
- Создать: `src/agent_engineering_kit/mcp_launcher.py`
- Создать: `tests/test_mcp_launcher.py`
- Изменить: `app.version`
- Изменить: `src/agent_engineering_kit/__init__.py`

**Интерфейсы:**
- Использует: `McpCredentialStore.load()`, разрешённый путь исполняемого файла, MCP-поля `args`, `environment` и `required_environment`.
- Предоставляет: `McpLaunchContract`, `write_launch_contract(paths, item, executable) -> Path`, `registration_command(paths, item, executable) -> tuple[str, list[str]]` и `launch(contract_path, *, paths, environ=None, exec_process=os.execvpe) -> None`.

- [ ] **Шаг 1: Написать падающие тесты контракта**

```python
def make_paths(tmp_path: Path) -> KitPaths:
    data = tmp_path / "data"
    return KitPaths(tmp_path / "repository", data, data / "runtime", data / "projects", data / "overrides")


def test_contract_contains_references_but_never_secret_values(tmp_path):
    paths = make_paths(tmp_path)
    item = {
        "id": "github",
        "args": ["stdio"],
        "environment": {"GITHUB_TOKEN": "env:GITHUB_PERSONAL_ACCESS_TOKEN"},
        "required_environment": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    }
    contract = write_launch_contract(paths, item, Path("/opt/github-mcp"))
    document = json.loads(contract.read_text())
    assert document["command"] == "/opt/github-mcp"
    assert document["environment"] == {"GITHUB_TOKEN": "GITHUB_PERSONAL_ACCESS_TOKEN"}
    assert "secret" not in contract.read_text().lower()


def test_registration_command_uses_python_module_and_absolute_contract(tmp_path):
    paths = make_paths(tmp_path)
    item = {
        "id": "github",
        "args": ["stdio"],
        "environment": {"GITHUB_TOKEN": "env:GITHUB_PERSONAL_ACCESS_TOKEN"},
        "required_environment": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    }
    command, args = registration_command(paths, item, Path("/opt/github-mcp"))
    assert command == sys.executable
    assert args[:2] == ["-m", "agent_engineering_kit.mcp_launcher"]
    assert Path(args[2]).is_absolute()
```

- [ ] **Шаг 2: Запустить тесты контракта и подтвердить падение**

Команда: `pytest -q tests/test_mcp_launcher.py -k 'contract or registration'`

Ожидание: тесты падают, потому что `mcp_launcher` ещё не существует.

- [ ] **Шаг 3: Реализовать версионируемые JSON-контракты**

```python
@dataclass(frozen=True)
class McpLaunchContract:
    version: int
    mcp_id: str
    command: str
    args: tuple[str, ...]
    environment: dict[str, str]
    required_environment: tuple[str, ...]


def registration_command(paths: KitPaths, item: dict[str, Any], executable: Path) -> tuple[str, list[str]]:
    contract = write_launch_contract(paths, item, executable)
    return sys.executable, ["-m", "agent_engineering_kit.mcp_launcher", str(contract.resolve())]
```

Хранить контракты в `<data>/installations/clients/shared/mcp-launchers/<mcp-id>.json`. Отклонять значения отображения без префикса `env:` и идентификаторы, небезопасные для имени файла. Записывать атомарно, не подставляя значения из окружения процесса или хранилища.

- [ ] **Шаг 4: Написать падающие тесты поведения launcher**

```python
def prepared_contract(tmp_path: Path) -> tuple[KitPaths, Path]:
    paths = make_paths(tmp_path)
    item = {
        "id": "sample",
        "args": ["serve"],
        "environment": {"TARGET": "env:SOURCE"},
        "required_environment": ["SOURCE"],
    }
    return paths, write_launch_contract(paths, item, Path("/opt/sample-mcp"))


def write_private_vault(paths: KitPaths, content: str) -> None:
    paths.secrets.mkdir(parents=True, mode=0o700)
    paths.secrets.chmod(0o700)
    vault = paths.secrets / "mcp-creds.env"
    vault.write_text(content, encoding="utf-8")
    vault.chmod(0o600)


def test_launch_overlays_only_declared_vault_values(tmp_path):
    paths, contract = prepared_contract(tmp_path)
    write_private_vault(paths, "SOURCE=vault-value\nUNUSED=hidden\n")
    calls = []
    launch(
        contract,
        environ={"SOURCE": "inherited", "KEEP": "yes", "UNUSED": "parent"},
        exec_process=lambda command, argv, env: calls.append((command, argv, env)),
        paths=paths,
    )
    assert calls[0][2]["TARGET"] == "vault-value"
    assert calls[0][2]["KEEP"] == "yes"
    assert calls[0][2]["UNUSED"] == "parent"
    assert "SOURCE" not in calls[0][2]


def test_launch_fails_before_exec_when_required_source_is_missing(tmp_path):
    paths, contract = prepared_contract(tmp_path)
    calls = []
    with pytest.raises(AgentKitError, match="SOURCE") as raised:
        launch(contract, environ={}, exec_process=lambda *args: calls.append(args), paths=paths)
    assert calls == []
    assert "vault-value" not in str(raised.value)
```

- [ ] **Шаг 5: Запустить тесты launcher и подтвердить ожидаемое падение**

Команда: `pytest -q tests/test_mcp_launcher.py -k 'launch_'`

Ожидание: тесты падают из-за отсутствия приоритета источников и проверки обязательных переменных при запуске.

- [ ] **Шаг 6: Реализовать изолированное окружение дочернего процесса и точку входа модуля**

Загрузить контракт, проверить версию `1`, прочитать хранилище и разрешить каждый объявленный источник выражением `vault.get(source) or environ.get(source)`. Удалять исходные имена из окружения дочернего процесса, когда они отличаются от целевых, чтобы не дублировать credentials. Проверить все обязательные источники до вызова `exec_process(command, [command, *args], child_environment)`.

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent_engineering_kit.mcp_launcher")
    parser.add_argument("contract", type=Path)
    args = parser.parse_args(argv)
    paths = resolve_paths()
    launch(args.contract, paths=paths)
    return 0
```

Ошибки называют только путь контракта, идентификатор MCP или отсутствующую переменную. Полное присваивание, окружение дочернего процесса и его вывод в сообщение не попадают.

- [ ] **Шаг 7: Запустить тесты launcher**

Команда: `pytest -q tests/test_mcp_launcher.py`

Ожидание: все тесты проходят.

- [ ] **Шаг 8: Поднять patch-версию и закоммитить поддержку launcher**

Set both version files to `0.8.7`, then run:

```bash
git add app.version src/agent_engineering_kit/__init__.py src/agent_engineering_kit/mcp_launcher.py tests/test_mcp_launcher.py
git commit -m "feat(mcp): add credential-aware launcher"
```

### Задача 3: Интеграция с нативной регистрацией клиентов

**Файлы:**
- Изменить: `src/agent_engineering_kit/clients.py`
- Изменить: `src/agent_engineering_kit/mcp_manager.py`
- Изменить: `mcp/registry.yaml`
- Изменить: `tests/test_clients.py`
- Изменить: `tests/test_mcp_manager.py`
- Изменить: `app.version`
- Изменить: `src/agent_engineering_kit/__init__.py`

**Интерфейсы:**
- Использует: `registration_command(paths, item, executable)` из задачи 2 и `McpCredentialStore.status()` из задачи 1.
- Предоставляет: управляемые регистрации Codex/Claude Code, указывающие на launcher для stdio MCP с `environment`; команды остальных транспортов не меняются.

- [ ] **Шаг 1: Написать падающие тесты нативной регистрации**

```python
def test_stdio_mcp_with_environment_is_registered_through_launcher(tmp_path, monkeypatch):
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    project = LogicalProject(root, root / ".ai-team/project.yaml", {
        "id": "project",
        "repositories": [{"id": "root", "path": "."}],
    })
    binary = paths.installations / "mcp/github/bin/github-mcp-server"
    binary.parent.mkdir(parents=True)
    binary.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr("agent_engineering_kit.clients.shutil.which", lambda name: f"/usr/bin/{name}" if name in {"codex", "claude"} else None)
    calls = []
    def runner(args, **kwargs):
        calls.append(list(args))
        if list(args[:3]) == ["git", "remote", "-v"]:
            return CommandResult(tuple(args), 0, "origin https://github.com/acme/repo.git (fetch)\n", "")
        return CommandResult(tuple(args), 1 if "get" in args else 0, "", "")
    state_path = register_native_mcp(repository, paths, project=project, access_profile="administrator", runner=runner)
    additions = [call for call in calls if "mcp" in call and "add" in call]
    rendered = json.dumps(additions)
    assert "agent_engineering_kit.mcp_launcher" in rendered
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" not in rendered
    assert "github-secret" not in rendered


def test_remote_oauth_registration_never_uses_credential_launcher(tmp_path, monkeypatch):
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    monkeypatch.setattr("agent_engineering_kit.clients.shutil.which", lambda name: f"/usr/bin/{name}" if name in {"codex", "claude"} else None)
    calls = []
    def runner(args, **kwargs):
        calls.append(list(args))
        return CommandResult(tuple(args), 1 if "get" in args else 0, "", "")
    register_native_mcp(repository, paths, runner=runner)
    context7 = next(call for call in calls if "add" in call and "agent-kit-context7" in call)
    assert "--url" in context7 or "--transport" in context7
    assert "mcp_launcher" not in " ".join(context7)
```

- [ ] **Шаг 2: Запустить целевые тесты клиентов и подтвердить падение проверки прямого запуска**

Команда: `pytest -q tests/test_clients.py -k 'environment_is_registered or oauth_registration'`

Ожидание: тест stdio падает, потому что текущая регистрация запускает бинарный файл MCP напрямую; исходный OAuth-сценарий проходит.

- [ ] **Шаг 3: Встроить launcher в проверку расхождений и команды добавления**

Перед проверкой stdio-записи вычислить:

```python
binary = manager.executable(item)
registration_binary, registration_args = (
    registration_command(paths, item, binary)
    if binary and item.get("environment")
    else (str(binary), list(item.get("args", [])))
)
```

Последовательно использовать `registration_binary` и `registration_args` при сравнении JSON Codex, текстовой проверке Claude и построении команды `mcp add`. Remote-регистрацию не менять. Удалять управляемые JSON-контракты, идентификаторы которых больше не требуются или больше не нуждаются в launcher; не удалять файлы за пределами `mcp-launchers/`.

- [ ] **Шаг 4: Расширить тест stdio-регистрации проверками отсутствующей обязательной переменной**

```python
# Append these assertions to test_stdio_mcp_with_environment_is_registered_through_launcher.
state = json.loads(state_path.read_text())
github = next(row for row in state["registrations"] if row.get("mcp") == "github" and row["client"] == "codex")
assert github["status"] == "CONFIG_REQUIRED"
assert github["missing_environment"] == ["GITHUB_PERSONAL_ACCESS_TOKEN"]
```

Регистрация всё равно создаётся: пользователь может импортировать credentials позже без повторного `resync`, а диагностический статус остаётся `CONFIG_REQUIRED`.

- [ ] **Шаг 5: Убрать зависимость активации через credentials от родительского shell**

Добавить `required_environment: [GITHUB_PERSONAL_ACCESS_TOKEN]` для GitHub и `required_environment: [SONARQUBE_TOKEN]` для SonarQube. Сохранить существующий обязательный токен и необязательный host Sentry. В `McpManager._project_signals` объединить непустые имена из `McpCredentialStore.load()` с `os.environ`: `SENTRY_ACCESS_TOKEN` активирует `sentry`, а remotes репозитория и файлы Sonar остаются сигналами GitHub, GitLab и SonarQube.

Добавить этот регрессионный тест в `tests/test_mcp_manager.py`:

```python
def test_sentry_vault_token_is_an_activation_signal(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    manager = McpManager(repository, paths)
    source = tmp_path / "credentials.env"
    source.write_text("SENTRY_ACCESS_TOKEN=fixture-token\n", encoding="utf-8")
    McpCredentialStore(paths).import_file(source, manager.available())
    sentry = next(item for item in manager.list() if item["id"] == "sentry")
    assert sentry["status"] != "inactive"
```

- [ ] **Шаг 6: Запустить все тесты клиентов и MCP manager**

Команда: `pytest -q tests/test_clients.py tests/test_mcp_manager.py`

Ожидание: все тесты проходят, ни вызовы, ни state JSON не содержат значения credentials.

- [ ] **Шаг 7: Поднять patch-версию и закоммитить интеграцию клиентов**

Set both version files to `0.8.8`, then run:

```bash
git add app.version src/agent_engineering_kit/__init__.py src/agent_engineering_kit/clients.py src/agent_engineering_kit/mcp_manager.py mcp/registry.yaml tests/test_clients.py tests/test_mcp_manager.py
git commit -m "feat(clients): register credential-aware mcp launchers"
```

### Задача 4: Жизненный цикл CLI и диагностика doctor

**Файлы:**
- Изменить: `src/agent_engineering_kit/cli.py`
- Изменить: `src/agent_engineering_kit/doctor.py`
- Изменить: `tests/test_cli.py`
- Создать или изменить: `tests/test_doctor.py`
- Изменить: `app.version`
- Изменить: `src/agent_engineering_kit/__init__.py`

**Интерфейсы:**
- Использует: `McpCredentialStore`, `McpManager.available`, текущий logical project и итоговый `mcp.access_profile`.
- Предоставляет: `agent-kit mcp creds import --from PATH`, `status`, `clear --yes`; ошибки doctor для отсутствующих обязательных credentials включённых stdio MCP.

- [ ] **Шаг 1: Написать падающие тесты parser для трёх команд**

```python
def test_mcp_creds_import_parser():
    args = _parser().parse_args(["mcp", "creds", "import", "--from", "local.env"])
    assert args.mcp_command == "creds"
    assert args.creds_command == "import"
    assert args.source == Path("local.env")


def test_mcp_creds_clear_requires_explicit_yes_flag_at_runtime():
    assert run(["mcp", "creds", "clear"]) == 2
```

- [ ] **Шаг 2: Запустить тесты parser и подтвердить падение**

Команда: `pytest -q tests/test_cli.py -k 'mcp_creds'`

Ожидание: тесты падают, потому что `creds` ещё не распознаётся как подкоманда MCP.

- [ ] **Шаг 3: Добавить parser и один специализированный обработчик**

```python
creds = mcp_subparsers.add_parser("creds", help="Управлять локальными credentials MCP")
creds_commands = creds.add_subparsers(dest="creds_command", required=True)
import_command = creds_commands.add_parser("import")
import_command.add_argument("--from", dest="source", required=True, type=Path)
creds_commands.add_parser("status")
clear_command = creds_commands.add_parser("clear")
clear_command.add_argument("--yes", action="store_true")
```

Реализовать `_handle_mcp_credentials(args, repository, paths, project)`: команды `import` и `status` получают список разрешённых имён из `_available_resources("mcp", ...)`. Команда `clear` без флага вызывает `AgentKitError("Удаление credentials требует --yes")`. Выводить только целевой путь после импорта, строки JSON со статусами или подтверждение удаления.

- [ ] **Шаг 4: Написать падающие тесты маскирования вывода и doctor**

```python
def test_mcp_creds_status_never_prints_value(isolated_data, capsys):
    source = isolated_data / "credentials.env"
    source.write_text("GITHUB_PERSONAL_ACCESS_TOKEN=top-secret\n", encoding="utf-8")
    assert run(["mcp", "creds", "import", "--from", str(source)]) == 0
    capsys.readouterr()
    assert run(["mcp", "creds", "status"]) == 0
    assert "top-secret" not in capsys.readouterr().out


def test_doctor_reports_missing_required_name_only(tmp_path, monkeypatch):
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    sentry = next(item for item in McpManager(repository, paths).available() if item["id"] == "sentry")
    monkeypatch.setattr(McpManager, "desired", lambda self, project=None, access_profile="readonly": [(sentry, object())])
    monkeypatch.setattr(McpManager, "is_enabled", lambda self, item, project=None: True)
    result = doctor(repository, paths)
    messages = "\n".join(item.message for item in result.diagnostics)
    assert "SENTRY_ACCESS_TOKEN" in messages
    assert "top-secret" not in messages
```

- [ ] **Шаг 5: Реализовать диагностику credentials в doctor**

Только для включённых целевых stdio MCP вычислять требования и сообщать отсутствующие обязательные имена с учётом `McpCredentialStore.load()` и `os.environ`. Не считать необязательные переменные ошибками. Не завершать `resync` ошибкой только потому, что пользователь собирается импортировать секрет после установки регистраций; явной проверкой готовности служит `doctor`.

- [ ] **Шаг 6: Запустить тесты CLI и doctor**

Команда: `pytest -q tests/test_cli.py tests/test_doctor.py`

Ожидание: все тесты проходят.

- [ ] **Шаг 7: Поднять patch-версию и закоммитить пользовательский жизненный цикл**

Set both version files to `0.8.9`, then run:

```bash
git add app.version src/agent_engineering_kit/__init__.py src/agent_engineering_kit/cli.py src/agent_engineering_kit/doctor.py tests/test_cli.py tests/test_doctor.py
git commit -m "feat(cli): manage mcp credentials safely"
```

### Задача 5: Контракт репозитория, git hygiene и русские инструкции

**Файлы:**
- Создать: `mcp-creds.example.env`
- Изменить: `.gitignore`
- Изменить: `.env.example`
- Изменить: `src/agent_engineering_kit/definitions.py`
- Изменить: `src/agent_engineering_kit/git_hygiene.py`
- Изменить: `tests/test_git_hygiene.py`
- Изменить: `tests/test_repository.py`
- Изменить: `README.md`
- Изменить: `mcp/README.md`
- Изменить: `clients/codex/README.md`
- Изменить: `clients/claude-code/README.md`
- Изменить: `clients/claude-desktop/README.md`
- Изменить: `clients/opencode/README.md`
- Изменить: `clients/cline/README.md`
- Изменить: `docs/INDEX.md`
- Изменить: `app.version`
- Изменить: `src/agent_engineering_kit/__init__.py`

**Интерфейсы:**
- Использует: публичные команды и поведение из задач 1–4.
- Предоставляет: распространяемый шаблон credentials, валидацию репозитория, защиту от утечки через Git и полную инструкцию оператора.

- [ ] **Шаг 1: Написать падающие тесты шаблона и git hygiene**

```python
def test_mcp_credential_template_covers_registry_environment_references():
    repository = Path(__file__).resolve().parents[1]
    result = validate_mcp(repository)
    assert result.ok, "\n".join(item.render() for item in result.diagnostics)


@pytest.mark.parametrize("name", ["mcp-creds.env", "mcp-creds.work.env"])
def test_git_hygiene_rejects_tracked_mcp_credentials(repository, name):
    path = repository / name
    path.write_text("TOKEN=fixture-value\n", encoding="utf-8")
    subprocess.run(["git", "-C", repository, "add", "-f", name], check=True)
    assert not validate_git_hygiene(repository).ok
```

- [ ] **Шаг 2: Запустить тесты репозитория и подтвердить отсутствие шаблона**

Команда: `pytest -q tests/test_repository.py tests/test_git_hygiene.py -k 'credential or mcp_creds'`

Ожидание: тесты падают, потому что специализированный шаблон и правила hygiene ещё отсутствуют.

- [ ] **Шаг 3: Добавить специализированный шаблон и валидацию**

Создать русскоязычный шаблон с комментариями и пустыми присваиваниями для каждой ссылки базового stdio MCP:

```dotenv
# Локальные credentials для stdio MCP. Файл с заполненными значениями не коммитьте.
GITHUB_PERSONAL_ACCESS_TOKEN=
SENTRY_ACCESS_TOKEN=
SENTRY_HOST=
SONARQUBE_TOKEN=

# Atlassian, GitLab и Context7 используют OAuth отдельно в каждом AI-клиенте.
```

Добавить `mcp-creds.env` и `mcp-creds.*.env` в `.gitignore`; сохранить исключение `!mcp-creds.example.env`. Оставить `.env.example` для совместимости и добавить в него русскую ссылку на специализированный шаблон. Изменить `validate_mcp`, чтобы каждая запись `env:NAME` и `required_environment` присутствовала в `mcp-creds.example.env`.

- [ ] **Шаг 4: Усилить Git hygiene, не запрещая пример**

Добавить точные правила чувствительных имён для `mcp-creds.env` и `mcp-creds.*.env`, явно исключив `mcp-creds.example.env`. Проверять tracked и staged пути через существующие точки входа валидации.

- [ ] **Шаг 5: Написать русскую эксплуатационную документацию**

README must include the complete sequence:

```bash
cp mcp-creds.example.env mcp-creds.env
# Заполнить только нужные значения.
agent-kit mcp creds import --from ./mcp-creds.env
agent-kit mcp creds status
agent-kit mcp enable github --scope global --resync
agent-kit doctor
agent-kit security scan
```

Объяснить, что ротация выполняется повторным `import` и применяется при следующем запуске MCP без `resync`; изменение определения или команды требует `resync`; `clear --yes` удаляет только machine-local хранилище. Добавить таблицу для Codex CLI, Claude Code, Claude Desktop, OpenCode и Cline с автоматической или ручной регистрацией. Явно указать: OAuth повторяется для каждого клиента или профиля, кроме осознанной схемы, где все клиенты используют один Docker MCP Gateway и OAuth-состояние принадлежит Docker Desktop.

Каждый `clients/*/README.md` описывает место включения MCP, устранение `AUTH_REQUIRED` в конкретном клиенте и запрет literal credentials в нативной конфигурации. `mcp/README.md` разделяет stdio env credentials, remote OAuth и владение Docker gateway.

- [ ] **Шаг 6: Добавить ссылку на план в индекс документации**

Add:

```markdown
- [План безопасной загрузки credentials для MCP](superpowers/plans/2026-10-23-mcp-credentials.md).
```

- [ ] **Шаг 7: Запустить проверки репозитория, hygiene и документации**

Команда: `pytest -q tests/test_repository.py tests/test_git_hygiene.py`

Ожидание: все тесты проходят.

Команда: `agent-kit validate --ci`

Ожидание: `Результат: OK`; ни одна проверка не читает локальное хранилище значений.

- [ ] **Шаг 8: Поднять minor-версию и закоммитить завершённый публичный контракт**

Set both version files to `0.9.0`, then run:

```bash
git add .gitignore .env.example mcp-creds.example.env app.version src/agent_engineering_kit/__init__.py src/agent_engineering_kit/definitions.py src/agent_engineering_kit/git_hygiene.py tests/test_git_hygiene.py tests/test_repository.py README.md mcp/README.md clients/codex/README.md clients/claude-code/README.md clients/claude-desktop/README.md clients/opencode/README.md clients/cline/README.md docs/INDEX.md
git commit -m "docs(mcp): document credential and oauth workflows"
```

### Задача 6: Полная проверка, аудит безопасности и готовность PR

**Файлы:**
- Изменять только файлы, необходимые для исправления упавшего приёмочного теста.

**Интерфейсы:**
- Использует: результаты всех предыдущих задач.
- Предоставляет: воспроизводимые доказательства, что секреты не сохраняются и не печатаются, а все поддерживаемые пути клиентов сохраняют ожидаемое поведение.

- [ ] **Шаг 1: Вместе запустить все целевые тесты credentials и клиентов**

Команды:

```bash
pytest -q tests/test_mcp_credentials.py tests/test_mcp_launcher.py tests/test_clients.py tests/test_cli.py tests/test_doctor.py tests/test_git_hygiene.py tests/test_repository.py
```

Ожидание: все тесты проходят.

- [ ] **Шаг 2: Запустить полный набор тестов**

Команда: `pytest -q`

Ожидание: все тесты проходят без зависимости от сети, домашнего каталога пользователя и локального хранилища.

- [ ] **Шаг 3: Запустить валидацию репозитория и проверки безопасности**

Команды:

```bash
agent-kit validate --ci
agent-kit validate git-hygiene
agent-kit validate security
```

Ожидание: все три команды завершаются сообщением `Результат: OK`.

- [ ] **Шаг 4: Доказать отсутствие тестового секрета в сгенерированных артефактах**

Using an isolated `AGENT_KIT_DATA_HOME`, import `AEK_ACCEPTANCE_SECRET_7f3c`, run the CLI status and a stubbed native registration test, then search only the generated state and client-installation directories:

```bash
acceptance_data="$(mktemp -d)"
AGENT_KIT_DATA_HOME="$acceptance_data" rg -n --fixed-strings 'AEK_ACCEPTANCE_SECRET_7f3c' "$acceptance_data/state" "$acceptance_data/installations/clients"
```

Ожидание: код возврата `1` и пустой вывод. Каноническое хранилище намеренно находится вне проверяемых путей и имеет режим `0600` на POSIX.

- [ ] **Шаг 5: Проверить diff ветки и при необходимости закоммитить только исправления**

Команды:

```bash
git diff --check main...HEAD
git status --short
git diff --stat main...HEAD
```

Ожидание: нет ошибок пробелов; показаны только запланированные файлы и пользовательские untracked `.ai/`, `uv.lock`. Если проверка потребовала исправления, один раз поднять patch-версию и закоммитить изменение scoped-сообщением Conventional Commit, соответствующим исправлению.

- [ ] **Шаг 6: Подготовить описание Pull Request**

В описании PR перечислить: путь и права хранилища, правила отказа parser, изоляцию launcher, поведение регистрации клиентов, владение OAuth каждым клиентом, миграцию с `.env.example`, выполненные команды и подтверждение отсутствия literal secret в diff.
