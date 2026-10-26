"""Приведение локального управляющего слоя к целевому состоянию."""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .clients import expose_native_instructions, expose_native_skills, register_native_mcp, sync_clients
from .component_state import Lifecycle
from .errors import AgentKitError
from .harness import resolve_harness
from .external_skills import ExternalSkillManager
from .io import atomic_write
from .mcp_manager import McpManager
from .override_service import initialize_override_workspace
from .paths import KitPaths, ensure_runtime
from .policy import effective_policy as resolve_effective_policy
from .project_skills import ProjectSkillRepositoryManager
from .projects import LogicalProject
from .overrides import validate_overrides
from .security_tools import SecurityToolManager
from .sync import revision, update_repository
from .validation import validate


@dataclass(frozen=True)
class ResyncReport:
    revision: str
    security: list[dict]
    skills: list[dict]
    mcp: list[dict]
    clients: list[str]
    changed: bool
    incomplete: list[str]
    project_skills: dict[str, object] | None = None


def build_session_manifest(
    *,
    revision: str,
    project_id: str | None,
    security: list[dict],
    skills: list[dict],
    mcp: list[dict],
    clients: list[str],
    harness: dict[str, object],
    effective_policy: Path,
    recorded_at: str,
    project_skills: dict[str, object] | None = None,
) -> dict[str, object]:
    """Собрать воспроизводимый снимок control plane для текущего сеанса."""
    return {
        "schema": "agent-engineering-kit/effective-environment/v2",
        "revision": revision,
        "recorded_at": recorded_at,
        "project_id": project_id,
        "harness": harness,
        "effective_policy_sha256": hashlib.sha256(effective_policy.read_bytes()).hexdigest(),
        "security": security,
        "skills": skills,
        "project_skills": project_skills,
        "mcp": mcp,
        "clients": clients,
    }


def resync(
    repository: Path,
    paths: KitPaths,
    *,
    project: LogicalProject | None = None,
    update_kit: bool = True,
    install_security: bool = True,
    expose_native: bool = True,
    force: bool = False,
) -> ResyncReport:
    if update_kit:
        update_repository(repository)
    ensure_runtime(paths)
    initialize_override_workspace(repository, paths)
    current_revision = revision(repository)
    repository_validation = validate(repository, paths, "all", include_local=True)
    if not repository_validation.ok:
        messages = "; ".join(item.message for item in repository_validation.diagnostics if item.severity == "ERROR")
        raise AgentKitError(f"Resync остановлен repository validation: {messages}")
    override_validation = validate_overrides(repository, paths.overrides, project.identifier if project else None)
    if not override_validation.ok:
        messages = "; ".join(item.message for item in override_validation.diagnostics if item.severity == "ERROR")
        raise AgentKitError(f"Resync остановлен local overrides validation: {messages}")

    security_manager = SecurityToolManager(repository, paths)
    if install_security:
        security_result = security_manager.install(force=force)
        if not security_result.ok:
            messages = "; ".join(item.message for item in security_result.diagnostics if item.severity == "ERROR")
            raise AgentKitError(f"Resync остановлен security installation: {messages}")
    security_state = security_manager.status()

    skill_manager = ExternalSkillManager(repository, paths, project_id=project.identifier if project else None)
    skill_state = skill_manager.resync(force=force)
    blocked = [item["id"] for item in skill_state if item.get("status") != Lifecycle.ACTIVE.value]
    if blocked:
        raise AgentKitError(f"Resync остановлен: external skills не ACTIVE: {', '.join(blocked)}")

    capability_resolution = resolve_effective_policy(repository, paths, project)
    mcp_access_profile = str(capability_resolution.values.get("mcp.access_profile", "readonly"))
    mcp_manager = McpManager(repository, paths)
    mcp_result = mcp_manager.install(
        project=project,
        access_profile=mcp_access_profile,
        force=force,
    )
    if not mcp_result.ok:
        messages = "; ".join(item.message for item in mcp_result.diagnostics if item.severity == "ERROR")
        raise AgentKitError(f"Resync остановлен MCP installation: {messages}")
    mcp_state = mcp_manager.list(project, access_profile=mcp_access_profile)

    project_skills = ProjectSkillRepositoryManager(repository, paths, project).resync().as_dict() if project else None
    project_id = project.identifier if project else None
    generated = sync_clients(
        repository,
        paths,
        project=project,
        project_id=project_id,
        capability_policy=capability_resolution.as_dict(),
    )
    incomplete: list[str] = []
    if expose_native:
        generated.extend(expose_native_skills(repository, paths, project=project, project_id=project_id))
        generated.extend(expose_native_instructions(repository, paths))
        registration_path = register_native_mcp(
            repository,
            paths,
            project=project,
            access_profile=mcp_access_profile,
        )
        generated.append(registration_path)
        registrations = json.loads(registration_path.read_text(encoding="utf-8")).get("registrations", [])
        required_mcp = {
            item["id"]
            for item, _ in mcp_manager.desired(project, access_profile=mcp_access_profile)
            if item.get("required") and mcp_manager.is_enabled(item, project)
        }
        registration_errors = [
            item for item in registrations
            if item.get("mcp") in required_mcp and item.get("status") == Lifecycle.ERROR.value
        ]
        if registration_errors:
            details = "; ".join(
                f"{item.get('client')}/{item.get('mcp')}: {item.get('reason') or 'registration error'}"
                for item in registration_errors
            )
            raise AgentKitError(f"Resync остановлен client MCP registration: {details}")
        incomplete = []
        for item in registrations:
            if item.get("status") not in {"AUTH_REQUIRED", "CONFIG_REQUIRED"} or not item.get("mcp"):
                continue
            severity = "required" if item.get("mcp") in required_mcp else "optional"
            incomplete.append(f"{item.get('client')}/{item.get('mcp')}: {item.get('status')} ({severity})")

    previous_path = paths.state / "effective-environment.json"
    previous = previous_path.read_text(encoding="utf-8") if previous_path.exists() else ""
    effective = build_session_manifest(
        revision=current_revision,
        project_id=project.identifier if project else None,
        security=security_state,
        skills=skill_manager.list(),
        mcp=mcp_state,
        clients=[str(path) for path in generated],
        harness=resolve_harness(
            repository,
            project.manifest if project else None,
            policy_values=capability_resolution.values,
        ),
        effective_policy=paths.installations / "clients" / "shared" / "effective-policy.json",
        recorded_at=datetime.now(timezone.utc).isoformat(),
        project_skills=project_skills,
    )
    serialized = json.dumps(effective, ensure_ascii=False, indent=2) + "\n"
    comparable_previous = ""
    if previous:
        try:
            previous_document = json.loads(previous)
            previous_document.pop("recorded_at", None)
            comparable_previous = json.dumps(previous_document, ensure_ascii=False, sort_keys=True)
        except json.JSONDecodeError:
            comparable_previous = previous
    comparable_current = dict(effective)
    comparable_current.pop("recorded_at", None)
    changed = comparable_previous != json.dumps(comparable_current, ensure_ascii=False, sort_keys=True)
    atomic_write(previous_path, serialized)
    atomic_write(
        paths.state / "session-revision.json",
        json.dumps({"revision": current_revision, "immutable_for_session": True}, ensure_ascii=False, indent=2) + "\n",
    )
    return ResyncReport(
        current_revision, security_state, skill_state, mcp_state,
        [str(path) for path in generated], changed, incomplete, project_skills,
    )
