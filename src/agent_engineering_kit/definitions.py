"""Validation structured metadata agents, skills и MCP."""

from __future__ import annotations

from pathlib import Path
import re

from .io import load_yaml, markdown_frontmatter
from .result import ValidationResult
from .schema import validate_instance


def validate_agents(repository: Path) -> ValidationResult:
    result = ValidationResult()
    schema = repository / "schemas" / "agent.schema.json"
    identifiers: set[str] = set()
    for path in sorted((repository / "agents").glob("*.md")):
        metadata = markdown_frontmatter(path)
        result.extend(validate_instance(metadata, schema, str(path)))
        identifier = metadata.get("id")
        if identifier in identifiers:
            result.error("agents", f"Повторяющийся agent ID: {identifier}")
        identifiers.add(identifier)
    if result.ok:
        result.info("agents", f"Agents валидны: {len(identifiers)}")
    return result


def validate_skills(repository: Path) -> ValidationResult:
    result = ValidationResult()
    schema = repository / "schemas" / "skill.schema.json"
    identifiers: set[str] = set()
    for path in sorted((repository / "skills" / "first-party").glob("*/SKILL.md")):
        metadata = markdown_frontmatter(path)
        result.extend(validate_instance(metadata, schema, str(path)))
        identifier = metadata.get("name")
        if identifier in identifiers:
            result.error("skills", f"Повторяющийся skill ID: {identifier}")
        identifiers.add(identifier)
    if result.ok:
        result.info("skills", f"Skills валидны: {len(identifiers)}")
    return result


def validate_mcp(repository: Path) -> ValidationResult:
    document = load_yaml(repository / "mcp" / "registry.yaml")
    result = validate_instance(document, repository / "schemas" / "mcp.schema.json", "mcp/registry.yaml")
    identifiers: set[str] = set()
    example_variables = {
        line.split("=", 1)[0]
        for line in (repository / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    for server in document.get("servers", []):
        identifier = server.get("id")
        if identifier in identifiers:
            result.error("mcp", f"Повторяющийся MCP ID: {identifier}")
        identifiers.add(identifier)
        for name, source in (server.get("environment") or {}).items():
            if not isinstance(source, str) or not source.startswith("env:"):
                result.error("mcp", f"MCP {identifier}: environment.{name} должен использовать env:VARIABLE")
            elif source.removeprefix("env:") not in example_variables:
                result.error("mcp", f"MCP {identifier}: {source} отсутствует в .env.example")
        image = (server.get("installation") or {}).get("image")
        if image and not re.search(r"@sha256:[0-9a-f]{64}$", image):
            result.error("mcp", f"MCP {identifier}: container image должен быть закреплён immutable digest")
    if result.ok:
        result.info("mcp", f"MCP registry валиден: {len(identifiers)}")
    return result


def validate_locks(repository: Path) -> ValidationResult:
    from .catalog import resolve_desired

    result = ValidationResult()
    for name in ("skills", "mcp", "security"):
        try:
            resolved = resolve_desired(repository, name)
            result.info("catalogs", f"{name}: catalog/lock согласованы, components={len(resolved)}")
        except Exception as error:
            result.error("catalogs", str(error))
    return result
