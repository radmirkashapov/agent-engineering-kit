"""Объяснение итоговой конфигурации и происхождения её значений."""

from __future__ import annotations

import json
from pathlib import Path

from .conventions import load_conventions
from .external_skills import ExternalSkillManager
from .harness import resolve_harness
from .io import markdown_frontmatter
from .overrides import apply_local_overrides
from .mcp_manager import McpManager
from .models import load_policy
from .paths import KitPaths
from .policy import effective_policy
from .projects import LogicalProject, find_project
from .sync import revision


def explain(repository: Path, paths: KitPaths, start: Path, *, output_format: str = "text") -> str:
    policy = load_policy(repository, local_path=paths.overrides / "models.yaml")
    project = find_project(start)
    conventions = load_conventions(repository, project)
    resolved_policy = effective_policy(repository, paths, project)
    if output_format == "json":
        return json.dumps({
            "revision": revision(repository),
            "project_id": project.identifier if project else None,
            "policy": resolved_policy.as_dict(),
            "conventions": conventions,
        }, ensure_ascii=False, indent=2) + "\n"
    if output_format != "text":
        raise ValueError(f"Неизвестный формат config explain: {output_format}")
    lines = ["Agent Engineering Kit", f"revision: {revision(repository)}", ""]
    lines.extend(["Logical project:", project.identifier if project else "не определён", ""])
    if project:
        lines.extend(["Project root:", str(project.root), ""])
    harness = resolve_harness(
        repository,
        project.manifest if project else None,
        policy_values=resolved_policy.values,
    )
    lines.extend(
        [
            "Harness:",
            f"control plane: {harness['control_plane']}",
            f"execution owner: {harness['execution_owner']}",
            f"preferred client: {harness['preferred_client']}",
            f"selected client: {harness['selected_client']}",
            "managed capabilities: " + ", ".join(harness["managed_capabilities"]),
            "delegated capabilities: " + ", ".join(harness["delegated_capabilities"]),
            "",
        ]
    )
    lines.extend(["Models:", f"corporate policy: {'active' if policy.corporate_active else 'empty'}", "effective allowed models:"])
    effective_models = resolved_policy.values.get("models.allowed", sorted(policy.runtime_allowed_ids))
    lines.extend(f"- {item}" for item in sorted(effective_models))
    lines.extend(["", "User-local models:"])
    lines.extend([f"- {item} (local-only)" for item in sorted(policy.local)] or ["- отсутствуют"])
    lines.extend(["", "Skills:"])
    skill_manager = ExternalSkillManager(repository, paths, project_id=project.identifier if project else None)
    for state in skill_manager.list():
        activation = "enabled" if state["enabled"] else "disabled"
        if state.get("source") == "first-party":
            lines.append(f"- {state['id']}: {activation}; {state['status']}; access: {state['access_reason']} (source: first-party; validation: PASS)")
        else:
            lines.append(f"- {state['id']}: {activation}; {state['status']}; access: {state['access_reason']} (source: {state['source']}; revision: {state.get('revision', state.get('desired_revision'))})")
    lines.extend(["", "Agents:"])
    agents = []
    for agent in sorted((repository / "agents").glob("*.md")):
        metadata = markdown_frontmatter(agent)
        agents.append({**metadata, "id": metadata.get("id", agent.stem)})
    for agent in apply_local_overrides(agents, paths.overrides, "agents", project.identifier if project else None):
        lines.append(f"- {agent['id']} (source: effective core/local)")
    lines.extend(["", "Local overlays:"])
    overlay_roots = [("user-global", paths.overrides / "global")]
    if project:
        overlay_roots.append(("user-project", paths.overrides / "projects" / project.identifier))
    overlays = [f"- {path.relative_to(root)} (source: {source})" for source, root in overlay_roots if root.exists() for path in sorted(root.rglob("*.yaml"))]
    lines.extend(overlays or ["- отсутствуют"])
    lines.extend(["", "MCP:"])
    for server in McpManager(repository, paths).list(
        project,
        access_profile=str(resolved_policy.values["mcp.access_profile"]),
    ):
        activation = "enabled" if server["enabled"] else "disabled"
        lines.append(f"- {server['id']}: {activation}; {server['status']}; access: {server['access_reason']}")
    lines.extend(["", "Memory:", str(paths.projects / project.identifier) if project else "не определена"])
    lines.extend(["", "Effective policy:"])
    for key, value in sorted(resolved_policy.values.items()):
        source = resolved_policy.provenance[key][-1]["source"]
        lines.append(f"- {key}: {value!r}; {resolved_policy.classifications[key]}; source: {source}")
    lines.extend(f"WARNING: {warning}" for warning in resolved_policy.warnings)
    return "\n".join(lines) + "\n"
