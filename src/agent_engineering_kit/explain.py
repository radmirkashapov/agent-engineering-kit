"""Explain effective configuration и provenance."""

from __future__ import annotations

from pathlib import Path

from .io import load_yaml, markdown_frontmatter
from .models import load_policy
from .paths import KitPaths
from .projects import LogicalProject, find_project
from .sync import revision


def explain(repository: Path, paths: KitPaths, start: Path) -> str:
    policy = load_policy(repository)
    project = find_project(start)
    lines = ["Agent Engineering Kit", f"revision: {revision(repository)}", ""]
    lines.extend(["Logical project:", project.identifier if project else "не определён", ""])
    if project:
        lines.extend(["Project root:", str(project.root), ""])
    lines.extend(["Models:", f"corporate policy: {'active' if policy.corporate_active else 'empty'}", "effective allowed models:"])
    lines.extend(f"- {item}" for item in sorted(policy.runtime_allowed_ids))
    lines.extend(["", "User-local models:"])
    lines.extend([f"- {item} (local-only)" for item in sorted(policy.local)] or ["- отсутствуют"])
    lines.extend(["", "Skills:"])
    for skill in sorted((repository / "skills").glob("*/SKILL.md")):
        metadata = markdown_frontmatter(skill)
        lines.append(f"- {metadata.get('id', skill.parent.name)} (source: core)")
    lines.extend(["", "Agents:"])
    for agent in sorted((repository / "agents").glob("*.md")):
        metadata = markdown_frontmatter(agent)
        lines.append(f"- {metadata.get('id', agent.stem)} (source: core)")
    lines.extend(["", "Local overlays:"])
    overlay_roots = [("user-global", paths.overrides / "global")]
    if project:
        overlay_roots.append(("user-project", paths.overrides / "projects" / project.identifier))
    overlays = [f"- {path.relative_to(root)} (source: {source})" for source, root in overlay_roots if root.exists() for path in sorted(root.rglob("*.yaml"))]
    lines.extend(overlays or ["- отсутствуют"])
    lines.extend(["", "MCP:"])
    for server in load_yaml(repository / "mcp" / "registry.yaml").get("servers", []):
        lines.append(f"- {server['id']}: {'enabled' if server.get('enabled', True) else 'disabled'}")
    lines.extend(["", "Memory:", str(paths.projects / project.identifier) if project else "не определена"])
    return "\n".join(lines) + "\n"
