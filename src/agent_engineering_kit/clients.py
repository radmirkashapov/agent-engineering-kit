"""Тонкие клиентские адаптеры, создаваемые только в локальной среде."""

from __future__ import annotations

import shutil
import json
import os
from collections import Counter
from pathlib import Path

from .errors import AgentKitError
from .definitions import is_english_text
from .external_skills import ExternalSkillManager
from .harness import load_harness_clients
from .io import atomic_write, load_yaml, markdown_frontmatter
from .paths import KitPaths, ensure_runtime
from .overrides import apply_local_overrides
from .process import run_command
from .result import ValidationResult


CLIENTS = ("codex", "claude-code", "claude-desktop", "opencode", "cline")


def _is_within(path: Path, root: Path) -> bool:
    try:
        Path(os.path.abspath(path)).relative_to(root.resolve())
        return True
    except ValueError:
        return False


def validate_clients(repository: Path) -> ValidationResult:
    result = ValidationResult()
    catalog = load_harness_clients(repository)
    catalog_by_id = {item["id"]: item for item in catalog}
    counts = Counter(item.get("id") for item in catalog)
    if set(catalog_by_id) != set(CLIENTS) or any(counts[client] != 1 for client in CLIENTS):
        result.error("clients", "catalog/clients.yaml должен описывать каждый поддерживаемый client adapter ровно один раз")
    for client in CLIENTS:
        directory = repository / "clients" / client
        adapter = directory / "adapter.yaml"
        readme = directory / "README.md"
        if not adapter.is_file() or not readme.is_file():
            result.error("clients", f"Неполный adapter {client}: нужны adapter.yaml и README.md")
            continue
        document = load_yaml(adapter)
        if document.get("id") != client:
            result.error("clients", f"clients/{client}/adapter.yaml: id должен совпадать с именем каталога")
        if document.get("entrypoint") != "AI.md":
            result.error("clients", f"Adapter {client} должен ссылаться на AI.md, а не копировать rules")
        description = catalog_by_id.get(client, {}).get("description")
        if not is_english_text(description):
            result.error("clients", f"{client}: default harness description должен быть содержательным и английским")
    if result.ok:
        result.info("clients", f"Thin adapters валидны: {len(CLIENTS)}")
    return result


def sync_clients(
    repository: Path,
    paths: KitPaths,
    *,
    project_id: str | None = None,
    capability_policy: dict | None = None,
) -> list[Path]:
    ensure_runtime(paths)
    generated: list[Path] = []
    skill_manager = ExternalSkillManager(repository, paths, project_id=project_id)
    skill_sources: dict[str, Path] = {}
    for item in skill_manager.available():
        if item["enabled"] and item.get("path"):
            skill_sources[item["id"]] = Path(item["path"])
    for item, _ in skill_manager.desired():
        active = skill_manager.active_path(item["id"])
        if active:
            for skill in sorted((active / "skills").glob("*/SKILL.md")):
                skill_sources[skill.parent.name] = skill.parent

    shared = paths.installations / "clients" / "shared" / "skills"
    shared.mkdir(parents=True, exist_ok=True)
    for stale in sorted(shared.iterdir()):
        if stale.name not in skill_sources:
            if stale.is_symlink() or stale.is_file():
                stale.unlink()
            else:
                shutil.rmtree(stale)
    for identifier, source in skill_sources.items():
        target = shared / identifier
        _managed_link(target, source, paths)

    agents = []
    for path in sorted((repository / "agents").glob("*.md")):
        metadata = markdown_frontmatter(path)
        agents.append({**metadata, "id": metadata.get("id", path.stem), "content": path.read_text(encoding="utf-8")})
    rules = [
        {
            "id": path.stem,
            "policy": "enforced" if path.stem in {"security", "context", "models"} else "configurable",
            "content": path.read_text(encoding="utf-8"),
        }
        for path in sorted((repository / "rules").glob("*.md"))
    ]
    effective_agents = apply_local_overrides(
        agents,
        paths.overrides,
        "agents",
        project_id,
        enforced={item["id"] for item in agents if item.get("policy") == "enforced"},
    )
    effective_rules = apply_local_overrides(
        rules,
        paths.overrides,
        "rules",
        project_id,
        enforced={item["id"] for item in rules if item["policy"] == "enforced"},
    )
    effective_policy = paths.installations / "clients" / "shared" / "effective-policy.json"
    atomic_write(
        effective_policy,
        json.dumps(
            {
                "version": 2,
                "agents": effective_agents,
                "rules": effective_rules,
                "capability_policy": capability_policy or {"values": {}, "provenance": {}, "warnings": []},
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
    )

    for client in CLIENTS:
        adapter = load_yaml(repository / "clients" / client / "adapter.yaml")
        target = paths.installations / "clients" / client / "adapter.yaml"
        content = (
            "# Сгенерировано agent-kit; локальный runtime, не Git.\n"
            f"kit_repository: {repository}\n"
            f"entrypoint: {repository / adapter['entrypoint']}\n"
            f"effective_policy: {effective_policy}\n"
            f"skills: {shared}\n"
            f"mcp_registry: {repository / 'mcp' / 'registry.yaml'}\n"
        )
        atomic_write(target, content)
        # Путь совместимости для прежнего `agent-kit sync`; каноническое состояние остаётся в installations/.
        atomic_write(paths.runtime / "clients" / client / "adapter.yaml", content)
        generated.append(target)
    return generated


def _managed_link(target: Path, source: Path, paths: KitPaths) -> None:
    """Создать только управляемую ссылку, не затирая пользовательский файл."""
    if target.is_symlink():
        if target.resolve() == source.resolve():
            return
        link_target = target.readlink()
        lexical_target = Path(os.path.abspath(target.parent / link_target))
        if _is_within(target, paths.installations) or _is_within(lexical_target, paths.installations):
            target.unlink()
        else:
            raise AgentKitError(f"Client exposure collision с пользовательским symlink: {target}")
    elif target.exists():
        managed_copy = target.is_dir() and (target / ".agent-kit-managed.json").is_file()
        try:
            target.resolve().relative_to(paths.installations.resolve())
        except ValueError as error:
            if not managed_copy:
                raise AgentKitError(f"Client exposure collision: {target}") from error
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(source, target_is_directory=True)
    except OSError:
        shutil.copytree(source, target)
        atomic_write(target / ".agent-kit-managed.json", json.dumps({"source": str(source)}, ensure_ascii=False) + "\n")


def expose_native_skills(repository: Path, paths: KitPaths, *, roots: tuple[Path, ...] | None = None, project_id: str | None = None) -> list[Path]:
    """Подключить shared skills к официальным user-level discovery paths."""
    sync_clients(repository, paths, project_id=project_id)
    shared = paths.installations / "clients" / "shared" / "skills"
    discovery_roots = roots or (
        Path.home() / ".agents" / "skills",  # Codex и OpenCode читают этот Agent Skills scope.
        Path.home() / ".claude" / "skills",
    )
    exposed: list[Path] = []
    for root in discovery_roots:
        for skill in shared.iterdir():
            target = root / skill.name
            _managed_link(target, skill.resolve(), paths)
            exposed.append(target)
    state_path = paths.state / "managed-skill-exposures.json"
    previous: list[str] = []
    if state_path.is_file():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8")).get("paths", [])
        except (OSError, json.JSONDecodeError):
            previous = []
    desired_paths = {str(path) for path in exposed}
    for value in previous:
        stale = Path(value)
        if value in desired_paths or not stale.exists() and not stale.is_symlink():
            continue
        managed_copy = stale.is_dir() and (stale / ".agent-kit-managed.json").is_file()
        link_target = stale.readlink() if stale.is_symlink() else None
        lexical_target = Path(os.path.abspath(stale.parent / link_target)) if link_target is not None else None
        managed_link = lexical_target is not None and _is_within(lexical_target, paths.installations)
        if managed_link:
            stale.unlink()
        elif managed_copy:
            shutil.rmtree(stale)
    atomic_write(state_path, json.dumps({"version": 1, "paths": sorted(desired_paths)}, ensure_ascii=False, indent=2) + "\n")
    return exposed


def expose_native_instructions(repository: Path, paths: KitPaths, *, home: Path | None = None) -> list[Path]:
    """Синхронизировать только managed block, сохраняя пользовательский текст."""
    user_home = home or Path.home()
    targets = (
        user_home / ".codex" / "AGENTS.md",
        user_home / ".claude" / "CLAUDE.md",
        user_home / ".config" / "opencode" / "AGENTS.md",
    )
    start = "<!-- agent-engineering-kit:start -->"
    end = "<!-- agent-engineering-kit:end -->"
    block = (
        f"{start}\n"
        f"Используй canonical instructions: {repository / 'AI.md'}\n"
        f"Применяй effective local agents/rules из: {paths.installations / 'clients' / 'shared' / 'effective-policy.json'}\n"
        "В начале новой session выполни `agent-kit resync`; не копируй global rules в project.\n"
        f"{end}"
    )
    generated: list[Path] = []
    for target in targets:
        existing = target.read_text(encoding="utf-8") if target.is_file() else ""
        if start in existing and end in existing:
            prefix, remainder = existing.split(start, 1)
            _, suffix = remainder.split(end, 1)
            content = prefix.rstrip() + "\n\n" + block + suffix
        else:
            content = existing.rstrip() + ("\n\n" if existing.strip() else "") + block + "\n"
        atomic_write(target, content)
        generated.append(target)
    return generated


def register_native_mcp(
    repository: Path,
    paths: KitPaths,
    *,
    project=None,
    access_profile: str = "readonly",
    runner=run_command,
) -> Path:
    """Добавить namespaced core MCP, не изменяя чужие client entries."""
    from .mcp_manager import McpManager

    manager = McpManager(repository, paths, runner=runner)
    available = {
        item["id"]: item
        for item in manager.available(project, access_profile=access_profile)
    }
    desired = {
        item["id"]: item
        for item, _ in manager.desired(project, access_profile=access_profile)
        if manager.is_enabled(item, project)
    }
    target = paths.state / "client-mcp-registrations.json"
    previous_rows: list[dict] = []
    if target.is_file():
        try:
            previous_rows = json.loads(target.read_text(encoding="utf-8")).get("registrations", [])
        except (OSError, json.JSONDecodeError):
            previous_rows = []
    previous_by_client: dict[str, set[str]] = {}
    for row in previous_rows:
        if row.get("client") and row.get("mcp"):
            previous_by_client.setdefault(row["client"], set()).add(row["mcp"])

    rows: list[dict] = []
    clients = (("codex", shutil.which("codex")), ("claude-code", shutil.which("claude")))
    for client, executable in clients:
        previous_ids = previous_by_client.get(client, set())
        if not executable:
            preserved_ids = sorted(previous_ids)
            rows.extend(
                {"client": client, "mcp": identifier, "status": "NOT_SUPPORTED", "reason": "CLI не найден; синхронизация managed registration отложена"}
                for identifier in preserved_ids
            )
            if not preserved_ids:
                rows.append({"client": client, "status": "NOT_SUPPORTED", "reason": "CLI не найден"})
            continue
        managed_ids = set(available) | previous_ids
        for identifier in sorted(managed_ids - set(desired)):
            name = f"agent-kit-{identifier}"
            probe = runner(
                [executable, "mcp", "get", name, "--json"] if client == "codex" else [executable, "mcp", "get", name],
                cwd=paths.state,
            )
            item = available.get(identifier)
            status = "DISABLED" if not item or not item["enabled"] else "inactive"
            reason = item["access_reason"] if item else "removed:catalog"
            if not probe.ok:
                rows.append({"client": client, "mcp": identifier, "status": status, "changed": False, "desired_verified": True, "reason": reason})
                continue
            remove = [executable, "mcp", "remove", name]
            if client == "claude-code":
                remove.extend(["--scope", "user"])
            removed = runner(remove, cwd=paths.state)
            if not removed.ok:
                rows.append({"client": client, "mcp": identifier, "status": "ERROR", "changed": False, "desired_verified": False, "reason": "не удалось удалить запрещённую managed registration"})
                continue
            rows.append({"client": client, "mcp": identifier, "status": status, "changed": True, "desired_verified": True, "reason": reason})
        for identifier, item in desired.items():
            name = f"agent-kit-{identifier}"
            # Некоторые клиенты запускают stdio-сервер во время проверки. Изолируем
            # его временные файлы от логического проекта и репозитория Kit.
            probe = runner(
                [executable, "mcp", "get", name, "--json"] if client == "codex" else [executable, "mcp", "get", name],
                cwd=paths.state,
            )
            installation = item["installation"]
            binary = manager.executable(item) if installation["type"] != "remote" else None
            expected_args = item.get("args", [])
            matches = False
            if probe.ok and client == "codex":
                try:
                    transport = json.loads(probe.stdout).get("transport", {})
                    matches = (
                        transport.get("url") == installation.get("endpoint")
                        if installation["type"] == "remote"
                        else transport.get("command") == str(binary) and transport.get("args", []) == expected_args
                    )
                except json.JSONDecodeError:
                    matches = False
            elif probe.ok:
                expected_values = [installation["endpoint"]] if installation["type"] == "remote" else [str(binary), *expected_args]
                matches = all(value in probe.stdout for value in expected_values)
            if matches:
                status = "AUTH_REQUIRED" if installation.get("authentication") == "oauth" else "ACTIVE"
                rows.append({"client": client, "mcp": identifier, "status": status, "changed": False, "desired_verified": True})
                continue
            if probe.ok:
                remove = [executable, "mcp", "remove", name]
                if client == "claude-code":
                    remove.extend(["--scope", "user"])
                removed = runner(remove, cwd=paths.state)
                if not removed.ok:
                    rows.append({"client": client, "mcp": identifier, "status": "ERROR", "changed": False, "reason": "не удалось заменить drifted managed registration"})
                    continue
            if installation["type"] == "remote":
                command = (
                    [executable, "mcp", "add", name, "--url", installation["endpoint"]]
                    if client == "codex"
                    else [executable, "mcp", "add", "--transport", "http", "--scope", "user", name, installation["endpoint"]]
                )
            else:
                if not binary:
                    rows.append({"client": client, "mcp": identifier, "status": "ERROR", "reason": "executable не найден"})
                    continue
                command = [executable, "mcp", "add"]
                if client == "claude-code":
                    command.extend(["--scope", "user", name, "--", str(binary), *item.get("args", [])])
                else:
                    command.extend([name, "--", str(binary), *item.get("args", [])])
            added = runner(command, cwd=paths.state)
            status = ("AUTH_REQUIRED" if installation.get("authentication") == "oauth" else "ACTIVE") if added.ok else "ERROR"
            rows.append({"client": client, "mcp": identifier, "status": status, "changed": added.ok, "desired_verified": added.ok, "reason": "OAuth может потребовать интерактивного подтверждения при первом использовании" if status == "AUTH_REQUIRED" else ("" if added.ok else (added.stderr or added.stdout)[-1000:])})
    for client in ("claude-desktop", "opencode", "cline"):
        for identifier, item in desired.items():
            rows.append({
                "client": client,
                "mcp": identifier,
                "required": bool(item.get("required")),
                "status": "CONFIG_REQUIRED",
                "contract": f"clients/{client}/README.md",
            })
    atomic_write(target, json.dumps({"version": 1, "registrations": rows}, ensure_ascii=False, indent=2) + "\n")
    return target
