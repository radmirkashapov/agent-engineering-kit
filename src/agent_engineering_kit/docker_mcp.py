"""Управляемый адаптер выделенного профиля Docker MCP Toolkit."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from .errors import AgentKitError
from .io import atomic_write, load_yaml
from .paths import KitPaths, ensure_runtime
from .process import CommandResult, run_command
from .schema import validate_instance


Runner = Callable[..., CommandResult]


def _server_name(uri: str) -> str:
    parsed = urlsplit(uri)
    return Path(parsed.path).name or parsed.netloc


def confirmed_docker_routes(paths: KitPaths, project_id: str | None) -> tuple[set[str], dict[str, Any] | None]:
    """Прочитать только успешно подтверждённый routing snapshot."""
    target = paths.state / "docker-mcp-toolkit.json"
    if not target.is_file():
        return set(), None
    try:
        state = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set(), None
    if state.get("status") != "SYNCED" or state.get("project_id") != project_id:
        return set(), state
    return {
        identifier
        for identifier, route in state.get("routes", {}).items()
        if route == "docker"
    }, state


class DockerMcpToolkit:
    def __init__(
        self,
        repository: Path,
        paths: KitPaths,
        *,
        runner: Runner = run_command,
        docker_executable: str | None = None,
    ) -> None:
        self.repository = repository
        self.paths = paths
        self.runner = runner
        self.docker_executable = docker_executable if docker_executable is not None else shutil.which("docker")

    def effective_config(self, project_id: str | None) -> dict[str, Any]:
        config = load_yaml(self.repository / "mcp" / "docker-toolkit.yaml")
        for path in (
            self.paths.overrides / "global" / "docker-toolkit.yaml",
            self.paths.overrides / "projects" / str(project_id) / "docker-toolkit.yaml" if project_id else None,
        ):
            if path is None or not path.is_file():
                continue
            override = load_yaml(path)
            for key, value in override.items():
                if key == "mappings":
                    if not isinstance(value, dict):
                        raise AgentKitError(f"Docker Toolkit override {path}: mappings должен быть object")
                    config[key] = {**config.get(key, {}), **value}
                elif key != "version":
                    config[key] = value
        validation = validate_instance(
            config,
            self.repository / "schemas" / "docker-toolkit.schema.json",
            "effective Docker MCP Toolkit configuration",
        )
        if not validation.ok:
            messages = "; ".join(item.message for item in validation.diagnostics if item.severity == "ERROR")
            raise AgentKitError(f"Некорректная Docker Toolkit configuration: {messages}")
        for identifier, uri in config.get("mappings", {}).items():
            parsed = urlsplit(str(uri))
            if parsed.scheme not in {"catalog", "docker", "https", "file"}:
                raise AgentKitError(f"Docker mapping {identifier}: недопустимая URI scheme")
            if parsed.username or parsed.password:
                raise AgentKitError(f"Docker mapping {identifier}: credentials запрещены в URI")
        return config

    def set_enabled(self, *, scope: str, project_id: str | None, enabled: bool) -> Path:
        if scope == "project" and not project_id:
            raise AgentKitError("Project scope требует logical project")
        root = self.paths.overrides / ("global" if scope == "global" else f"projects/{project_id}")
        target = root / "docker-toolkit.yaml"
        atomic_write(
            target,
            "# Локальный выбор runtime Docker MCP Toolkit; файл не добавляется в Git.\n"
            f"version: 1\nenabled: {'true' if enabled else 'false'}\n",
        )
        if not enabled:
            state = self._read_state()
            if state:
                state["status"] = "PENDING"
                state["routes"] = {}
                atomic_write(
                    self.paths.state / "docker-mcp-toolkit.json",
                    json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                )
        return target

    def _toolkit_status(self) -> tuple[str, str]:
        if not self.docker_executable:
            return "NOT_INSTALLED", "Команда docker не найдена"
        probe = self.runner([self.docker_executable, "mcp", "--help"])
        if not probe.ok:
            return "CONFIG_REQUIRED", "Docker MCP Toolkit недоступен; обновите Docker Desktop и включите MCP Toolkit"
        return "READY", "Docker MCP Toolkit доступен"

    def _inspect_profile(self, profile: str) -> tuple[bool, dict[str, str]]:
        if not self.docker_executable:
            return False, {}
        inspected = self.runner([
            self.docker_executable, "mcp", "profile", "show", profile, "--format", "json",
        ])
        if not inspected.ok:
            return False, {}
        try:
            document = json.loads(inspected.stdout)
        except json.JSONDecodeError:
            return False, {}
        servers: dict[str, str] = {}
        for item in document.get("servers", []):
            if isinstance(item, str):
                servers[_server_name(item)] = item
            elif isinstance(item, dict) and item.get("uri"):
                servers[str(item.get("name") or _server_name(str(item["uri"])))]=str(item["uri"])
        return True, servers

    def _desired_ids(self, project: Any, access_profile: str) -> set[str]:
        from .mcp_manager import McpManager

        manager = McpManager(self.repository, self.paths, runner=self.runner)
        return {
            item["id"]
            for item, _ in manager.desired(project, access_profile=access_profile)
            if manager.is_enabled(item, project)
        }

    def plan(
        self,
        *,
        project: Any = None,
        access_profile: str = "readonly",
        desired_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        project_id = project.identifier if project else None
        config = self.effective_config(project_id)
        desired = set(desired_ids) if desired_ids is not None else self._desired_ids(project, access_profile)
        mappings = {key: str(value) for key, value in config.get("mappings", {}).items()}
        selected = {identifier: mappings[identifier] for identifier in sorted(desired & mappings.keys())} if config["enabled"] else {}
        toolkit_status, message = self._toolkit_status()
        routes = {
            identifier: (
                "unavailable" if config["enabled"] and identifier in mappings and toolkit_status != "READY"
                else "docker" if identifier in selected
                else "native"
            )
            for identifier in sorted(desired)
        }
        if toolkit_status != "READY":
            return {
                "status": toolkit_status if config["enabled"] else "DISABLED",
                "message": message,
                "profile": config["profile"],
                "routes": routes,
                "operations": [],
            }
        exists, current = self._inspect_profile(str(config["profile"]))
        previous_state = self._read_state()
        previously_managed = {
            key: str(value) for key, value in previous_state.get("managed_servers", {}).items()
        }
        operations: list[dict[str, Any]] = []
        if selected and not exists:
            operations.append({
                "action": "create",
                "command": [self.docker_executable, "mcp", "profile", "create", "--name", str(config["profile"])],
            })
        current_uris = set(current.values())
        for identifier, uri in selected.items():
            if uri not in current_uris:
                operations.append({
                    "action": "add",
                    "mcp": identifier,
                    "command": [
                        self.docker_executable, "mcp", "profile", "server", "add", str(config["profile"]),
                        "--server", uri,
                    ],
                })
        for identifier, uri in sorted(previously_managed.items()):
            if identifier not in selected and uri in current_uris:
                operations.append({
                    "action": "remove",
                    "mcp": identifier,
                    "command": [
                        self.docker_executable, "mcp", "profile", "server", "remove", str(config["profile"]),
                        "--name", _server_name(uri),
                    ],
                })
        return {
            "status": "DRIFT" if operations else ("READY" if config["enabled"] else "DISABLED"),
            "message": message,
            "profile": config["profile"],
            "project_id": project_id,
            "routes": routes,
            "selected": selected,
            "current_servers": current,
            "operations": operations,
        }

    def _read_state(self) -> dict[str, Any]:
        target = self.paths.state / "docker-mcp-toolkit.json"
        if not target.is_file():
            return {}
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def status(self, *, project: Any = None, access_profile: str = "readonly") -> dict[str, Any]:
        plan = self.plan(project=project, access_profile=access_profile)
        confirmed, state = confirmed_docker_routes(self.paths, project.identifier if project else None)
        return {**plan, "confirmed_routes": sorted(confirmed), "last_sync": state}

    def sync(
        self,
        *,
        project: Any = None,
        access_profile: str = "readonly",
        desired_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        ensure_runtime(self.paths)
        plan = self.plan(project=project, access_profile=access_profile, desired_ids=desired_ids)
        if plan["status"] in {"NOT_INSTALLED", "CONFIG_REQUIRED"}:
            return plan
        for operation in plan["operations"]:
            completed = self.runner(operation["command"])
            if not completed.ok:
                failed = {**plan, "status": "ERROR", "failed_operation": operation, "reason": (completed.stderr or completed.stdout)[-2000:]}
                atomic_write(self.paths.state / "docker-mcp-toolkit.json", json.dumps(failed, ensure_ascii=False, indent=2) + "\n")
                return failed
        config = self.effective_config(project.identifier if project else None)
        selected = dict(plan.get("selected", {}))
        exists, current = self._inspect_profile(str(config["profile"]))
        if selected and (not exists or not set(selected.values()) <= set(current.values())):
            failed = {**plan, "status": "ERROR", "reason": "Docker profile не подтвердил desired servers"}
            atomic_write(self.paths.state / "docker-mcp-toolkit.json", json.dumps(failed, ensure_ascii=False, indent=2) + "\n")
            return failed
        state = {
            "version": 1,
            "status": "SYNCED",
            "project_id": project.identifier if project else None,
            "profile": config["profile"],
            "gateway_registration": config["gateway_registration"],
            "routes": {identifier: "docker" for identifier in selected},
            "managed_servers": selected,
            "current_servers": current,
        }
        atomic_write(self.paths.state / "docker-mcp-toolkit.json", json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        return state
