"""MCP desired state, installation status и project-conditional activation."""

from __future__ import annotations

import os
import platform
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

from .access import resolve_access
from .catalog import LockedComponent, resolve_desired
from .component_state import Lifecycle, read_state, write_state
from .errors import AgentKitError
from .paths import KitPaths, ensure_runtime
from .overrides import apply_local_overrides
from .process import CommandResult, run_command
from .projects import LogicalProject
from .result import ValidationResult
from .schema import validate_instance


class McpManager:
    def __init__(self, repository: Path, paths: KitPaths, *, runner: Callable[..., CommandResult] = run_command) -> None:
        self.repository = repository
        self.paths = paths
        self.runner = runner

    def available(self, project: LogicalProject | None = None) -> list[dict[str, Any]]:
        """Вернуть полный каталог MCP с итоговым решением о доступе."""
        resolved = resolve_desired(self.repository, "mcp")
        items = [item for item, _ in resolved]
        enforced = {item["id"] for item in items if item.get("policy") == "locked" or item.get("required")}
        effective = apply_local_overrides(items, self.paths.overrides, "mcp", project.identifier if project else None, enforced=enforced)
        effective_by_id = {item["id"]: item for item in effective}
        validation = validate_instance(
            {"version": 1, "servers": effective},
            self.repository / "schemas" / "mcp.schema.json",
            "effective MCP configuration",
        )
        if not validation.ok:
            errors = "; ".join(item.message for item in validation.diagnostics if item.severity == "ERROR")
            raise AgentKitError(f"Некорректный effective MCP override: {errors}")
        decisions = resolve_access(set(effective_by_id) | {item["id"] for item in items}, self.paths.overrides, "mcp", project.identifier if project else None)
        available: list[dict[str, Any]] = []
        for catalog_item in items:
            identifier = catalog_item["id"]
            item = effective_by_id.get(identifier, catalog_item)
            decision = decisions[identifier]
            disabled_by_override = identifier not in effective_by_id
            available.append(
                {
                    **item,
                    "enabled": decision.enabled and not disabled_by_override,
                    "access_reason": "disabled:override" if disabled_by_override else decision.reason,
                }
            )
        return available

    def desired(self, project: LogicalProject | None = None) -> list[tuple[dict[str, Any], LockedComponent]]:
        locks = {item["id"]: lock for item, lock in resolve_desired(self.repository, "mcp")}
        return [(item, locks[item["id"]]) for item in self.available(project) if item["enabled"]]

    def component_root(self, identifier: str) -> Path:
        return self.paths.installations / "mcp" / identifier

    def executable(self, item: dict[str, Any]) -> Path | None:
        command = item.get("command") or item.get("installation", {}).get("command")
        if not command:
            return None
        candidate = self.component_root(item["id"]) / "bin" / command
        if platform.system() == "Windows" and candidate.with_suffix(".exe").is_file():
            return candidate.with_suffix(".exe")
        if candidate.is_file():
            return candidate
        if item.get("installation", {}).get("type") == "external-command":
            discovered = shutil.which(command)
            return Path(discovered) if discovered else None
        return None

    def _project_signals(self, project: LogicalProject | None) -> set[str]:
        signals: set[str] = set()
        if not project:
            return signals
        for repository in project.manifest.get("repositories", []):
            root = (project.root / repository["path"]).resolve()
            remotes = self.runner(["git", "remote", "-v"], cwd=root) if (root / ".git").exists() else None
            remote_text = remotes.stdout.lower() if remotes and remotes.ok else ""
            if "github.com" in remote_text:
                signals.add("github")
            if "gitlab" in remote_text:
                signals.add("gitlab")
            if any((root / name).exists() for name in ("sonar-project.properties", ".sonarcloud.properties")):
                signals.add("sonar")
            if any(root.rglob("package.json")):
                signals.add("web")
        if any(os.environ.get(name) for name in ("JIRA_URL", "ATLASSIAN_SITE_URL", "CONFLUENCE_URL")):
            signals.add("atlassian")
        return signals

    def is_enabled(self, item: dict[str, Any], project: LogicalProject | None = None) -> bool:
        activation = item.get("activation", "always")
        return activation == "always" or activation in self._project_signals(project)

    def install(self, *, project: LogicalProject | None = None, force: bool = False) -> ValidationResult:
        ensure_runtime(self.paths)
        result = ValidationResult()
        for item, lock in self.desired(project):
            identifier = item["id"]
            if not self.is_enabled(item, project):
                result.info("mcp-install", f"{identifier}: не активирован project signals")
                continue
            installation = item["installation"]
            current = read_state(self.paths, "mcp", identifier)
            executable = self.executable(item)
            available = installation["type"] == "remote" or bool(executable)
            if installation["type"] == "external-command" and installation.get("image") and executable:
                available = self.runner([str(executable), "image", "inspect", installation["image"]]).ok
            if available and current.get("status") == Lifecycle.ACTIVE.value and current.get("revision") == lock.revision and not force:
                result.info("mcp-install", f"{identifier}: уже ACTIVE")
                continue
            if installation["type"] == "remote":
                write_state(self.paths, "mcp", identifier, Lifecycle.ACTIVE, revision=lock.revision, version=lock.version, endpoint=installation["endpoint"], transport=item["transport"])
                result.info("mcp-install", f"{identifier}: remote endpoint ACTIVE")
                continue
            if installation["type"] == "external-command":
                if not executable:
                    write_state(self.paths, "mcp", identifier, Lifecycle.NOT_INSTALLED, revision=lock.revision, reason="command не найден")
                    (result.error if item.get("required") else result.warning)("mcp-install", f"{identifier}: command не найден")
                    continue
                if image := installation.get("image"):
                    pulled = self.runner([str(executable), "pull", image])
                    if not pulled.ok:
                        write_state(self.paths, "mcp", identifier, Lifecycle.ERROR, revision=lock.revision, reason=(pulled.stderr or pulled.stdout)[-2000:])
                        (result.error if item.get("required") else result.warning)("mcp-install", f"{identifier}: pinned image не установлен")
                        continue
            elif installation["type"] == "self-update":
                if not executable:
                    write_state(self.paths, "mcp", identifier, Lifecycle.NOT_INSTALLED, revision=lock.revision, reason="bootstrap command не найден")
                    result.error("mcp-install", f"{identifier}: bootstrap command не найден")
                    continue
                version_check = self.runner([str(executable), "--version"])
                if lock.version.lstrip("v") not in version_check.stdout or force:
                    completed = self.runner([str(executable), *installation.get("update_args", ["update", "-y"])])
                    if not completed.ok:
                        write_state(self.paths, "mcp", identifier, Lifecycle.ERROR, revision=lock.revision, reason=(completed.stderr or completed.stdout)[-2000:])
                        result.error("mcp-install", f"{identifier}: self-update завершился ошибкой")
                        continue
                    verified = self.runner([str(executable), "--version"])
                    if lock.version.lstrip("v") not in (verified.stdout + verified.stderr):
                        write_state(self.paths, "mcp", identifier, Lifecycle.ERROR, revision=lock.revision, reason="version после update не совпадает с lock")
                        result.error("mcp-install", f"{identifier}: установленная version не совпадает с lock")
                        continue
            elif installation["type"] == "pinned-release-installer":
                candidate = self.paths.state / "candidates" / "mcp" / f"{identifier}-{uuid.uuid4().hex}"
                candidate.parent.mkdir(parents=True, exist_ok=True)
                cloned = self.runner(["git", "clone", "--quiet", "--no-checkout", item["source"]["repository"], str(candidate)])
                checked_out = self.runner(["git", "checkout", "--quiet", "--detach", lock.revision], cwd=candidate) if cloned.ok else cloned
                windows = platform.system() == "Windows"
                script_name = installation["scripts"]["windows" if windows else "posix"]
                script = candidate / script_name
                root = self.component_root(identifier)
                (root / "bin").mkdir(parents=True, exist_ok=True)
                environment = {"CBM_DOWNLOAD_URL": installation["download_base"].replace("{version}", lock.version)}
                install_command = (["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script), "--dir", str(root / "bin"), "--skip-config"] if windows else ["bash", str(script), "--dir", str(root / "bin"), "--skip-config"])
                completed = self.runner(install_command, env=environment) if checked_out.ok and script.is_file() else checked_out
                executable = self.executable(item)
                if not completed.ok or not executable:
                    write_state(self.paths, "mcp", identifier, Lifecycle.ERROR, revision=lock.revision, reason=(completed.stderr or completed.stdout)[-4000:])
                    result.error("mcp-install", f"{identifier}: pinned release installation завершилась ошибкой")
                    continue
                verified = self.runner([str(executable), "--version"])
                if lock.version.lstrip("v") not in (verified.stdout + verified.stderr):
                    write_state(self.paths, "mcp", identifier, Lifecycle.ERROR, revision=lock.revision, reason="release binary version не совпадает с lock")
                    result.error("mcp-install", f"{identifier}: release version не совпадает с lock")
                    continue
                shutil.rmtree(candidate, ignore_errors=True)
            elif installation["type"] == "uv-tool":
                root = self.component_root(identifier)
                (root / "bin").mkdir(parents=True, exist_ok=True)
                environment = {"UV_TOOL_DIR": str(root / "tool"), "UV_TOOL_BIN_DIR": str(root / "bin")}
                completed = self.runner([
                    "uv", "tool", "install", "--force", "--python", str(installation.get("python", "3.13")),
                    installation["requirement"].replace("{version}", lock.version).replace("{revision}", lock.revision),
                ], env=environment)
                executable = self.executable(item)
                if not completed.ok or not executable:
                    write_state(self.paths, "mcp", identifier, Lifecycle.ERROR, revision=lock.revision, reason=(completed.stderr or completed.stdout)[-2000:])
                    result.error("mcp-install", f"{identifier}: uv installation завершилась ошибкой")
                    continue
            else:
                result.error("mcp-install", f"{identifier}: неизвестный installation.type")
                continue
            write_state(self.paths, "mcp", identifier, Lifecycle.ACTIVE, revision=lock.revision, version=lock.version, executable=str(executable), transport=item["transport"])
            result.info("mcp-install", f"{identifier}: ACTIVE {lock.version}")
        return result

    def list(self, project: LogicalProject | None = None) -> list[dict[str, Any]]:
        values = []
        locks = {item["id"]: lock for item, lock in resolve_desired(self.repository, "mcp")}
        for item in self.available(project):
            lock = locks[item["id"]]
            state = read_state(self.paths, "mcp", item["id"])
            access_enabled = bool(item["enabled"])
            activation_enabled = access_enabled and self.is_enabled(item, project)
            installation = item["installation"]
            executable = self.executable(item)
            available = bool(installation.get("endpoint")) if installation["type"] == "remote" else bool(executable)
            if activation_enabled and installation["type"] == "external-command" and installation.get("image") and executable:
                available = self.runner([str(executable), "image", "inspect", installation["image"]]).ok
            status = state.get("status", Lifecycle.NOT_INSTALLED.value)
            if not access_enabled:
                status = "DISABLED"
            elif not activation_enabled:
                status = "inactive"
            elif available and status == Lifecycle.NOT_INSTALLED.value:
                status = Lifecycle.INSTALLED.value
            elif not available and status == Lifecycle.ACTIVE.value:
                status = Lifecycle.NOT_INSTALLED.value
            if activation_enabled and state.get("revision") and state.get("revision") != lock.revision:
                status = Lifecycle.OUTDATED.value
            values.append({**state, "id": item["id"], "category": item["category"], "enabled": activation_enabled, "access_reason": item["access_reason"], "available": available, "status": status, "desired_revision": lock.revision, "source": item["source"]["repository"]})
        return values

    def doctor(self, project: LogicalProject | None = None) -> ValidationResult:
        result = ValidationResult()
        desired_by_id = {item["id"]: item for item, _ in self.desired(project)}
        for state in self.list(project):
            if state["status"] == "DISABLED":
                result.info("mcp-doctor", f"{state['id']}: отключён пользователем ({state['access_reason']})")
            elif state["status"] == "inactive":
                result.info("mcp-doctor", f"{state['id']}: не активирован признаками проекта")
            elif state["available"]:
                result.info("mcp-doctor", f"{state['id']}: {state['status']}")
            elif desired_by_id[state["id"]].get("required"):
                result.error("mcp-doctor", f"{state['id']}: required MCP недоступен")
            else:
                result.warning("mcp-doctor", f"{state['id']}: optional MCP недоступен")
        return result
