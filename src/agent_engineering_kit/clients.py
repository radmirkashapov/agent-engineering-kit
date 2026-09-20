"""Thin adapters: generation идёт только в local runtime."""

from __future__ import annotations

import shutil
import json
import os
from pathlib import Path

from .errors import AgentKitError
from .external_skills import ExternalSkillManager
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
    if result.ok:
        result.info("clients", f"Thin adapters валидны: {len(CLIENTS)}")
    return result


def sync_clients(repository: Path, paths: KitPaths, *, project_id: str | None = None) -> list[Path]:
    ensure_runtime(paths)
    generated: list[Path] = []
    skill_manager = ExternalSkillManager(repository, paths, project_id=project_id)
    skill_sources: dict[str, Path] = {}
    first_party_items: list[dict] = []
    for skill in sorted((repository / "skills" / "first-party").glob("*/SKILL.md")):
        metadata = markdown_frontmatter(skill)
        first_party_items.append({"id": skill.parent.name, "path": str(skill.parent), "policy": metadata.get("policy", "configurable")})
    enforced = {item["id"] for item in first_party_items if item["policy"] == "enforced"}
    for item in apply_local_overrides(first_party_items, paths.overrides, "skills", project_id, enforced=enforced):
        if item.get("path"):
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
    effective_agents = apply_local_overrides(agents, paths.overrides, "agents", project_id)
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
        json.dumps({"version": 1, "agents": effective_agents, "rules": effective_rules}, ensure_ascii=False, indent=2) + "\n",
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
        # Compatibility location для прежнего `agent-kit sync`; canonical state остаётся в installations/.
        compatibility_content = content.replace(f"skills: {shared}", f"skills: {repository / 'skills'}")
        atomic_write(paths.runtime / "clients" / client / "adapter.yaml", compatibility_content)
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


def register_native_mcp(repository: Path, paths: KitPaths, *, project=None, runner=run_command) -> Path:
    """Добавить namespaced core MCP, не изменяя чужие client entries."""
    from .mcp_manager import McpManager

    manager = McpManager(repository, paths, runner=runner)
    desired = {item["id"]: item for item, _ in manager.desired(project) if manager.is_enabled(item, project)}
    rows: list[dict] = []
    clients = (("codex", shutil.which("codex")), ("claude-code", shutil.which("claude")))
    for client, executable in clients:
        if not executable:
            rows.append({"client": client, "status": "NOT_SUPPORTED", "reason": "CLI не найден"})
            continue
        for identifier, item in desired.items():
            name = f"agent-kit-{identifier}"
            # Некоторые clients запускают stdio-server во время probe. Изолируем
            # побочные runtime-файлы от logical project и самого kit repository.
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
    target = paths.state / "client-mcp-registrations.json"
    atomic_write(target, json.dumps({"version": 1, "registrations": rows}, ensure_ascii=False, indent=2) + "\n")
    return target
