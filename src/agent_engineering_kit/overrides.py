"""Validation локальных overlays с явными режимами conflict resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .access import validate_access
from .io import load_yaml, markdown_frontmatter
from .result import ValidationResult
from .schema import validate_instance


KINDS = ("skills", "agents", "mcp", "rules")
MODES = {"extend", "replace", "disable"}
ENFORCED_FIELDS = {"id", "required", "policy", "security", "source"}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def apply_local_overrides(
    items: list[dict[str, Any]],
    override_root: Path,
    kind: str,
    project_id: str | None = None,
    *,
    enforced: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Применить global, затем project overlays; catalogs остаются immutable."""
    effective = {item["id"]: dict(item) for item in items}
    roots = [override_root / "global"]
    if project_id:
        roots.append(override_root / "projects" / project_id)
    for root in roots:
        directory = root / kind
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            document = load_yaml(path)
            target = document.get("target")
            override = document.get("override", {})
            mode = override.get("mode")
            if target not in effective or mode not in MODES:
                continue
            if mode == "disable":
                effective.pop(target, None)
                continue
            value = override.get("value", {})
            if not isinstance(value, dict):
                continue
            value = dict(value)
            declared_path = value.get("path")
            if isinstance(declared_path, str) and not Path(declared_path).is_absolute():
                value["path"] = str((path.parent / declared_path).resolve())
            if enforced and target in enforced:
                value = {key: item for key, item in value.items() if key not in ENFORCED_FIELDS}
            effective[target] = ({"id": target, **value} if mode == "replace" else _deep_merge(effective[target], value))
    return list(effective.values())


def _core_ids(repository: Path, kind: str) -> dict[str, bool]:
    if kind == "mcp":
        registry_path = repository / "mcp" / "registry.yaml"
        if not registry_path.is_file():
            return {}
        registry = load_yaml(registry_path)
        return {item["id"]: item.get("policy") == "locked" for item in registry.get("servers", [])}
    root = repository / kind
    found: dict[str, bool] = {}
    if not root.exists():
        return found
    if kind == "skills":
        skill_root = root / "first-party" if (root / "first-party").is_dir() else root
        candidates = skill_root.iterdir()
    else:
        candidates = root.glob("*.md")
    for path in candidates:
        metadata: dict[str, Any] = {}
        identifier = path.stem
        if path.is_dir() and (path / "SKILL.md").is_file():
            metadata = markdown_frontmatter(path / "SKILL.md")
            identifier = str(metadata.get("name", metadata.get("id", path.name)))
        elif path.suffix == ".md":
            metadata = markdown_frontmatter(path)
            identifier = str(metadata.get("id", path.stem))
        found[identifier] = metadata.get("policy") == "enforced" or (kind == "rules" and identifier in {"security", "context", "models"})
    if kind == "skills":
        catalog_path = repository / "catalog" / "skills.yaml"
        if catalog_path.is_file():
            registry = load_yaml(catalog_path)
            for item in registry.get("skills", []):
                found[item["id"]] = bool(item.get("required"))
    return found


def validate_overrides(repository: Path, override_root: Path, project_id: str | None = None) -> ValidationResult:
    result = ValidationResult()
    roots = [override_root / "global"]
    if project_id:
        roots.append(override_root / "projects" / project_id)
    checked = 0
    for root in roots:
        for kind in KINDS:
            directory = root / kind
            if not directory.exists():
                continue
            core = _core_ids(repository, kind)
            for path in sorted(directory.glob("*.yaml")):
                checked += 1
                document = load_yaml(path)
                result.extend(validate_instance(document, repository / "schemas" / "override.schema.json", str(path)))
                target = document.get("target")
                override = document.get("override", {})
                mode = override.get("mode") if isinstance(override, dict) else None
                if mode not in MODES:
                    result.error("overrides", f"{path}: override.mode должен быть extend, replace или disable")
                    continue
                if target not in core:
                    result.error("overrides", f"{path}: неизвестный target {target!r} для {kind}")
                elif core[target] and mode == "replace":
                    result.error("overrides", f"{path}: нельзя применить {mode} к enforced {kind[:-1]} {target!r}")
                elif core[target] and isinstance(override.get("value"), dict) and ENFORCED_FIELDS & set(override["value"]):
                    result.error("overrides", f"{path}: enforced fields нельзя ослаблять: {sorted(ENFORCED_FIELDS & set(override['value']))}")
    result.extend(
        validate_access(
            {
                "mcp": set(_core_ids(repository, "mcp")),
                "skills": set(_core_ids(repository, "skills")),
            },
            override_root,
            project_id,
        )
    )
    registry_path = repository / "mcp" / "registry.yaml"
    if registry_path.is_file():
        registry = load_yaml(registry_path)
        servers = registry.get("servers", [])
        enforced_mcp = {item["id"] for item in servers if item.get("policy") == "locked" or item.get("required")}
        effective_mcp = apply_local_overrides(servers, override_root, "mcp", project_id, enforced=enforced_mcp)
        result.extend(
            validate_instance(
                {"version": 1, "servers": effective_mcp},
                repository / "schemas" / "mcp.schema.json",
                "effective MCP overrides",
            )
        )
    if result.ok:
        result.info("overrides", f"Local overrides валидны; проверено: {checked}")
    return result
