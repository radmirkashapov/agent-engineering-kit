"""Тонкие клиентские адаптеры, создаваемые только в локальной среде."""

from __future__ import annotations

import shutil
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from .access import resolve_access
from .catalog import resolve_desired
from .component_state import Lifecycle, read_state
from .errors import AgentKitError
from .definitions import is_english_text, validate_skill_directory
from .external_skills import ExternalSkillManager
from .harness import load_harness_clients
from .io import atomic_write, load_json, load_yaml, markdown_frontmatter
from .paths import KitPaths, ensure_runtime
from .overrides import apply_local_overrides
from .process import run_command
from .projects import LogicalProject
from .project_skills import ProjectSkillRepositoryManager, redact_url
from .result import ValidationResult


CLIENTS = ("codex", "claude-code", "claude-desktop", "opencode", "cline")


def _opencode_config_path(home: Path) -> Path:
    """Выбрать единственный глобальный config OpenCode без project-level записи."""
    json_path = home / ".config" / "opencode" / "opencode.json"
    jsonc_path = home / ".config" / "opencode" / "opencode.jsonc"
    return jsonc_path if jsonc_path.is_file() else json_path


def _load_opencode_config(path: Path) -> dict:
    if not path.is_file():
        return {"$schema": "https://opencode.ai/config.json"}
    try:
        raw = path.read_text(encoding="utf-8")
        # Поддерживаем JSONC, сохраняя семантику пользовательских полей при merge.
        cleaned = re.sub(r"(?m)^\s*//[^\n]*|/\*[\s\S]*?\*/", "", raw)
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        document = json.loads(cleaned)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AgentKitError(f"Некорректный JSON OpenCode: {path}") from error
    if not isinstance(document, dict):
        raise AgentKitError(f"OpenCode config должен быть object: {path}")
    return document


def _sync_opencode_mcp(
    paths: KitPaths,
    desired: dict[str, dict],
    manager,
    endpoint_values: dict[str, str],
    *,
    home: Path | None = None,
) -> tuple[str, bool, str]:
    """Слить только managed `agent-kit-*` entries с глобальным OpenCode config."""
    from .mcp_endpoint import resolved_endpoint
    from .mcp_launcher import registration_command

    config_path = _opencode_config_path(home or Path.home())
    document = _load_opencode_config(config_path)
    mcp = document.setdefault("mcp", {})
    if not isinstance(mcp, dict):
        raise AgentKitError(f"OpenCode mcp должен быть object: {config_path}")
    servers = mcp.setdefault("servers", {})
    if not isinstance(servers, dict):
        raise AgentKitError(f"OpenCode mcp.servers должен быть object: {config_path}")
    previous = json.dumps(servers, ensure_ascii=False, sort_keys=True)
    expected_names = {str(item.get("registration_name", f"agent-kit-{identifier}")) for identifier, item in desired.items()}
    for name in list(servers):
        if isinstance(name, str) and name.startswith("agent-kit-") and name not in expected_names:
            del servers[name]
    for identifier, item in desired.items():
        name = str(item.get("registration_name", f"agent-kit-{identifier}"))
        installation = item["installation"]
        if installation["type"] == "remote":
            entry = {"type": "remote", "url": resolved_endpoint(item, endpoint_values)}
        else:
            binary = manager.executable(item)
            if binary is None:
                continue
            command, args = (
                registration_command(paths, item, binary)
                if item.get("environment") or item.get("required_environment")
                else (str(binary), list(item.get("args", [])))
            )
            entry = {"type": "local", "command": [command, *args]}
        # Пользовательские поля чужих MCP не читаются и не меняются; managed
        # server целиком принадлежит Kit и атомарно приводится к desired state.
        servers[name] = entry
    changed = previous != json.dumps(servers, ensure_ascii=False, sort_keys=True) or not config_path.is_file()
    if changed:
        try:
            atomic_write(config_path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        except OSError:
            return "CONFIG_REQUIRED", False, str(config_path)
    return "SYNCED", changed, str(config_path)


def _sync_opencode_instructions(
    repository: Path,
    paths: KitPaths,
    *,
    home: Path,
    agent_kit_enabled: bool,
) -> Path:
    """Подключить canonical AI.md через нативное поле OpenCode instructions."""
    config_path = _opencode_config_path(home)
    document = _load_opencode_config(config_path)
    configured = document.get("instructions", [])
    if not isinstance(configured, list) or not all(isinstance(item, str) for item in configured):
        raise AgentKitError(f"OpenCode instructions должен быть массивом строк: {config_path}")
    managed_path = str((repository / "AI.md").resolve())
    state_path = paths.state / "opencode-managed-instructions.json"
    owned: set[str] = set()
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            candidates = state.get("paths", [])
            if isinstance(candidates, list) and all(isinstance(item, str) for item in candidates):
                owned = set(candidates)
        except (OSError, json.JSONDecodeError):
            pass
    updated = list(configured)
    if agent_kit_enabled:
        if managed_path not in updated:
            updated.append(managed_path)
            owned.add(managed_path)
    elif managed_path in owned:
        updated = [item for item in updated if item != managed_path]
        owned.discard(managed_path)
    changed = updated != configured or not config_path.is_file()
    if changed:
        atomic_write(config_path, json.dumps({**document, "instructions": updated}, ensure_ascii=False, indent=2) + "\n")
    atomic_write(state_path, json.dumps({"version": 1, "paths": sorted(owned)}, ensure_ascii=False, indent=2) + "\n")
    return config_path


@dataclass(frozen=True)
class EffectiveSkillSource:
    identifier: str
    path: Path
    source: str
    revision: str | None
    priority: int
    source_url: str | None = None
    catalog_id: str | None = None
    shadowed: tuple[EffectiveSkillSource, ...] = ()
    enabled: bool = True
    access_reason: str = "allowed:catalog"

    def as_dict(self) -> dict:
        return {
            "path": str(self.path), "source": self.source, "revision": self.revision,
            "priority": self.priority, "source_url": redact_url(self.source_url), "catalog_id": self.catalog_id,
            "enabled": self.enabled, "access_reason": self.access_reason,
            "shadowed": [item.as_dict() for item in sorted(self.shadowed, key=lambda item: item.priority)],
        }


def _merge_skill_source(target: dict[str, EffectiveSkillSource], candidate: EffectiveSkillSource) -> None:
    current = target.get(candidate.identifier)
    if current is None:
        target[candidate.identifier] = candidate
    elif candidate.priority >= current.priority:
        target[candidate.identifier] = replace(candidate, shadowed=(*current.shadowed, replace(current, shadowed=())))
    else:
        target[candidate.identifier] = replace(current, shadowed=(*current.shadowed, candidate))


def effective_skill_sources(
    repository: Path,
    paths: KitPaths,
    project: LogicalProject | None = None,
    project_id: str | None = None,
    *,
    include_disabled: bool = False,
) -> dict[str, EffectiveSkillSource]:
    """Разрешить все skill layers единым precedence/override/ACL pipeline."""
    project_id = project.identifier if project is not None else project_id
    sources: dict[str, EffectiveSkillSource] = {}
    for document in sorted((repository / "skills/first-party").glob("*/SKILL.md")):
        metadata = markdown_frontmatter(document)
        identifier = metadata.get("name") or metadata.get("id") or document.parent.name
        _merge_skill_source(sources, EffectiveSkillSource(identifier, document.parent, "built-in", None, 10))

    catalog = [item for item, _ in resolve_desired(repository, "skills")]
    catalog_urls = {item["id"]: item.get("source", {}).get("repository") for item in catalog}
    effective_catalog = apply_local_overrides(catalog, paths.overrides, "skills", project_id)
    access = resolve_access({item["id"] for item in catalog}, paths.overrides, "skills", project_id)
    manager = ExternalSkillManager(repository, paths, project_id=project_id)
    local_packages = []
    for item in effective_catalog:
        identifier = item["id"]
        if not access[identifier].enabled:
            continue
        if item.get("path"):
            local_packages.append(item)
        active = manager.active_path(identifier)
        if active:
            state = read_state(paths, "skills", identifier)
            revision = state.get("revision") if state.get("status") == Lifecycle.ACTIVE.value else state.get("active_revision")
            for document in sorted((active / "skills").glob("*/SKILL.md")):
                # Замена пакета отключает его capability directories, кроме
                # одноимённого источника, сохраняемого как shadowed provenance.
                if item.get("path") and document.parent.name != identifier:
                    continue
                _merge_skill_source(sources, EffectiveSkillSource(
                    document.parent.name, document.parent, "external-catalog", revision, 20,
                    catalog_urls[identifier], catalog_id=identifier,
                ))

    if project is not None:
        project_manager = ProjectSkillRepositoryManager(repository, paths, project)
        active_skills = project_manager.active_skills()
        if active_skills:
            # status.json описывает последнюю попытку и может содержать URL
            # отклонённого источника; provenance принадлежит только active.json.
            active = load_json(project_manager.root / "active.json")
            revision = active.get("active_revision")
            if (not isinstance(revision, str) or not isinstance(active.get("source_url"), str)
                    or active.get("project_id") != project.identifier or active.get("state") != "ACTIVE"
                    or active.get("resolved_revision") != revision or active.get("skills") != list(active_skills)
                    or any(path != project_manager.root / "revisions" / revision / "skills" / identifier
                           for identifier, path in active_skills.items())):
                raise AgentKitError("active pointer project-skills изменился во время публикации; повторите sync")
            for identifier, path in active_skills.items():
                _merge_skill_source(sources, EffectiveSkillSource(
                    identifier, path, "project-skills", revision, 30, active["source_url"],
                ))

    # Overrides выбирают целый каталог после всех переносимых источников.
    items = [{"id": identifier, "path": str(source.path)} for identifier, source in sources.items()]
    effective = apply_local_overrides(items, paths.overrides, "skills", project_id)
    enabled = {item["id"] for item in [*effective, *local_packages]}
    for item in [*effective, *local_packages]:
        identifier = item["id"]
        if not item.get("path"):
            raise AgentKitError(f"Некорректный local skill override: {identifier} требует path")
        path = Path(item["path"])
        current = sources.get(identifier)
        if current is not None and path == current.path and current.source != "built-in":
            continue
        validation = validate_skill_directory(path, repository / "schemas/skill.schema.json", identifier,
                                              f"effective skill {identifier!r}")
        if not validation.ok:
            errors = "; ".join(item.message for item in validation.diagnostics if item.severity == "ERROR")
            raise AgentKitError(f"Некорректный local skill override: {errors}")
        if current is not None and path == current.path:
            continue
        _merge_skill_source(sources, EffectiveSkillSource(
            identifier, path, "local-override", None, 40, catalog_id=current.catalog_id if current else None,
        ))
    # Capability directories внешнего пакета наследуют доступ к catalog ID.
    access = resolve_access({source.catalog_id or identifier for identifier, source in sources.items()},
                            paths.overrides, "skills", project_id)
    resolved: dict[str, EffectiveSkillSource] = {}
    for identifier, source in sources.items():
        decision = access[source.catalog_id or identifier]
        override_enabled = identifier in enabled
        resolved[identifier] = replace(
            source,
            enabled=override_enabled and decision.enabled,
            access_reason=decision.reason if override_enabled else "disabled:override",
        )
    return resolved if include_disabled else {
        identifier: source for identifier, source in resolved.items() if source.enabled
    }


def effective_skill_inventory(
    repository: Path, paths: KitPaths, project: LogicalProject | None = None,
) -> list[dict]:
    """Вернуть CLI-инвентарь из того же resolver, который публикует clients."""
    project_id = project.identifier if project else None
    rows = {
        item["id"]: item
        for item in ExternalSkillManager(repository, paths, project_id=project_id).list()
    }
    for identifier, source in effective_skill_sources(
        repository, paths, project, project_id, include_disabled=True,
    ).items():
        metadata = markdown_frontmatter(source.path / "SKILL.md")
        rows[identifier] = {
            **metadata,
            "id": identifier,
            **source.as_dict(),
            "status": Lifecycle.ACTIVE.value if source.enabled else "DISABLED",
        }
    return [rows[identifier] for identifier in sorted(rows)]


def project_skill_status_report(
    repository: Path, paths: KitPaths, project: LogicalProject,
) -> dict[str, object]:
    """Дополнить lifecycle status текущим branch selection и provenance."""
    manager = ProjectSkillRepositoryManager(repository, paths, project)
    with manager.read_snapshot():
        report = manager.status().as_dict()
        selection = manager.inspect()
        sources = effective_skill_sources(repository, paths, project, include_disabled=True)
        provenance: dict[str, dict] = {}
        collisions: dict[str, list[str]] = {}
        for identifier in manager.active_skills():
            source = sources.get(identifier)
            if source is None:
                continue
            provenance[identifier] = source.as_dict()
            layers = [*source.shadowed, replace(source, shadowed=())]
            names = [item.source for item in sorted(layers, key=lambda item: item.priority)]
            if len(names) > 1:
                collisions[identifier] = names
    return {
        **report,
        "requested_branch": selection["requested_branch"],
        "local_override_applied": selection["local_override_applied"],
        "provenance": provenance,
        "collisions": collisions,
    }


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
    project: LogicalProject | None = None,
    project_id: str | None = None,
    capability_policy: dict | None = None,
) -> list[Path]:
    ensure_runtime(paths)
    generated: list[Path] = []
    project_id = project.identifier if project else project_id
    skill_sources = effective_skill_sources(repository, paths, project, project_id)

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
        _managed_link(target, source.path, paths)
    atomic_write(
        shared.parent / "skills-provenance.json",
        json.dumps({"version": 1, "skills": {identifier: source.as_dict()
                   for identifier, source in sorted(skill_sources.items())}}, ensure_ascii=False, indent=2) + "\n",
    )

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


def expose_native_skills(
    repository: Path, paths: KitPaths, *, roots: tuple[Path, ...] | None = None,
    project: LogicalProject | None = None, project_id: str | None = None,
) -> list[Path]:
    """Подключить shared skills к официальным user-level discovery paths."""
    sync_clients(repository, paths, project=project, project_id=project_id)
    shared = paths.installations / "clients" / "shared" / "skills"
    discovery_roots = roots or (
        Path.home() / ".agents" / "skills",  # Codex и OpenCode читают этот Agent Skills scope.
        Path.home() / ".claude" / "skills",
    )
    exposed: list[Path] = []
    for root in discovery_roots:
        for skill in shared.iterdir():
            target = root / skill.name
            _managed_link(target, skill, paths)
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


def expose_native_instructions(
    repository: Path,
    paths: KitPaths,
    *,
    home: Path | None = None,
    agent_kit_enabled: bool = True,
) -> list[Path]:
    """Синхронизировать managed block, сохраняя пользовательский текст."""
    user_home = home or Path.home()
    targets = (
        user_home / ".codex" / "AGENTS.md",
        user_home / ".claude" / "CLAUDE.md",
        user_home / ".config" / "opencode" / "AGENTS.md",
    )
    start = "<!-- agent-engineering-kit:start -->"
    end = "<!-- agent-engineering-kit:end -->"
    if agent_kit_enabled:
        block = (
            f"{start}\n"
            f"Используй canonical instructions: {repository / 'AI.md'}\n"
            f"Применяй effective local agents/rules из: {paths.installations / 'clients' / 'shared' / 'effective-policy.json'}\n"
            "В начале новой session выполни `agent-kit resync`; не копируй global rules в project.\n"
            f"{end}"
        )
    else:
        block = (
            f"{start}\n"
            "Agent Engineering Kit глобально отключён на этой машине.\n"
            "Не применяй профили, роли, rules и skills Agent Engineering Kit к агентам.\n"
            "Для повторного включения выполни `agent-kit enable`.\n"
            f"{end}"
        )
    generated: list[Path] = []
    # OpenCode поддерживает instructions в JSON/JSONC. Используем это поле,
    # а AGENTS.md оставляем как совместимый discovery bridge для старых версий.
    generated.append(_sync_opencode_instructions(
        repository, paths, home=user_home, agent_kit_enabled=agent_kit_enabled,
    ))
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
    from .mcp_endpoint import resolved_endpoint
    from .mcp_credentials import McpCredentialStore
    from .mcp_launcher import registration_command
    from .docker_mcp import confirmed_docker_routes

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
    project_id = project.identifier if project else None
    docker_routes, docker_state = confirmed_docker_routes(paths, project_id)
    # Подтверждённый snapshot не может расширять более свежую effective policy.
    docker_routes &= set(desired)
    for identifier in docker_routes:
        desired.pop(identifier, None)
    gateway = {
        "id": "docker-gateway",
        "category": "runtime",
        "required": False,
        "enabled": bool(docker_routes),
        "access_reason": "runtime:docker-toolkit",
        "registration_name": str((docker_state or {}).get("gateway_registration", "agent-kit-docker")),
        "command": "docker",
        "args": ["mcp", "gateway", "run", "--profile", str((docker_state or {}).get("profile", "agent-engineering-kit"))],
        "installation": {"type": "external-command", "command": "docker"},
        "source": {"repository": "https://docs.docker.com/ai/mcp-catalog-and-toolkit/"},
    }
    available["docker-gateway"] = gateway
    if docker_routes:
        desired["docker-gateway"] = gateway
    launcher_ids = {
        identifier for identifier, item in desired.items()
        if item["installation"]["type"] != "remote" and (item.get("environment") or item.get("required_environment"))
    }
    launcher_root = paths.installations / "clients" / "shared" / "mcp-launchers"
    launcher_directories = (
        paths.installations,
        paths.installations / "clients",
        paths.installations / "clients" / "shared",
        launcher_root,
    )
    if all(not directory.is_symlink() for directory in launcher_directories) and launcher_root.is_dir():
        for stale in launcher_root.glob("*.json"):
            if stale.stem not in launcher_ids and (stale.is_symlink() or stale.is_file()):
                stale.unlink()
    credential_store = McpCredentialStore(paths)
    credential_status = {row["name"]: row["status"] for row in credential_store.status(desired.values())}
    endpoint_values = {**os.environ, **credential_store.load()}
    try:
        opencode_status, opencode_changed, opencode_path = _sync_opencode_mcp(
            paths, desired, manager, endpoint_values,
            # Инъецированный runner используется только в тестах и dry интеграциях:
            # не позволяем им менять настоящий user-level config.
            home=None if runner is run_command else paths.data / "test-home",
        )
    except AgentKitError:
        opencode_status, opencode_changed, opencode_path = "CONFIG_REQUIRED", False, ""
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
            item = available.get(identifier)
            name = str((item or {}).get("registration_name", f"agent-kit-{identifier}"))
            probe = runner(
                [executable, "mcp", "get", name, "--json"] if client == "codex" else [executable, "mcp", "get", name],
                cwd=paths.state,
            )
            status = "DOCKER_ROUTED" if identifier in docker_routes else ("DISABLED" if not item or not item["enabled"] else "inactive")
            reason = "runtime:docker-toolkit" if identifier in docker_routes else (item["access_reason"] if item else "removed:catalog")
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
            name = str(item.get("registration_name", f"agent-kit-{identifier}"))
            # Некоторые клиенты запускают stdio-сервер во время проверки. Изолируем
            # его временные файлы от логического проекта и репозитория Kit.
            probe = runner(
                [executable, "mcp", "get", name, "--json"] if client == "codex" else [executable, "mcp", "get", name],
                cwd=paths.state,
            )
            installation = item["installation"]
            binary = manager.executable(item) if installation["type"] != "remote" else None
            registration_binary, expected_args = (
                registration_command(paths, item, binary)
                if binary and (item.get("environment") or item.get("required_environment"))
                else (str(binary), list(item.get("args", [])))
            )
            missing_environment = sorted(
                name for name in item.get("required_environment", [])
                if credential_status.get(name) != "SET" and not os.environ.get(name)
            ) if installation["type"] != "remote" else []
            ready_status = (
                "AUTH_REQUIRED" if installation.get("authentication") == "oauth"
                else "CONFIG_REQUIRED" if missing_environment else "ACTIVE"
            )
            readiness = {"missing_environment": missing_environment} if missing_environment else {}
            matches = False
            if probe.ok and client == "codex":
                try:
                    transport = json.loads(probe.stdout).get("transport", {})
                    matches = (
                        transport.get("url") == resolved_endpoint(item, endpoint_values)
                        if installation["type"] == "remote"
                        else transport.get("command") == registration_binary and transport.get("args", []) == expected_args
                    )
                except json.JSONDecodeError:
                    matches = False
            elif probe.ok:
                expected_values = [resolved_endpoint(item, endpoint_values)] if installation["type"] == "remote" else [registration_binary, *expected_args]
                matches = all(value in probe.stdout for value in expected_values)
            if matches:
                rows.append({"client": client, "mcp": identifier, "status": ready_status, "changed": False, "desired_verified": True, **readiness})
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
                    [executable, "mcp", "add", name, "--url", resolved_endpoint(item, endpoint_values)]
                    if client == "codex"
                    else [executable, "mcp", "add", "--transport", "http", "--scope", "user", name, resolved_endpoint(item, endpoint_values)]
                )
            else:
                if not binary:
                    rows.append({"client": client, "mcp": identifier, "status": "ERROR", "reason": "executable не найден"})
                    continue
                command = [executable, "mcp", "add"]
                if client == "claude-code":
                    command.extend(["--scope", "user", name, "--", registration_binary, *expected_args])
                else:
                    command.extend([name, "--", registration_binary, *expected_args])
            added = runner(command, cwd=paths.state)
            status = ready_status if added.ok else "ERROR"
            rows.append({"client": client, "mcp": identifier, "status": status, "changed": added.ok, "desired_verified": added.ok, **readiness, "reason": "OAuth может потребовать интерактивного подтверждения при первом использовании" if status == "AUTH_REQUIRED" else ("" if added.ok else "не удалось зарегистрировать managed MCP")})
    for client in ("claude-desktop", "cline"):
        for identifier, item in desired.items():
            rows.append({
                "client": client,
                "mcp": identifier,
                "required": bool(item.get("required")),
                "status": "CONFIG_REQUIRED",
                "contract": f"clients/{client}/README.md",
            })
    for identifier, item in desired.items():
        rows.append({
            "client": "opencode",
            "mcp": identifier,
            "required": bool(item.get("required")),
            "status": opencode_status,
            "changed": opencode_changed,
            "path": opencode_path,
        })
    atomic_write(target, json.dumps({"version": 1, "registrations": rows}, ensure_ascii=False, indent=2) + "\n")
    return target
