"""Validation локальных overlays с явными режимами conflict resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import load_yaml, markdown_frontmatter
from .result import ValidationResult
from .schema import validate_instance


KINDS = ("skills", "agents", "mcp", "rules")
MODES = {"extend", "replace", "disable"}


def _core_ids(repository: Path, kind: str) -> dict[str, bool]:
    if kind == "mcp":
        registry = load_yaml(repository / "mcp" / "registry.yaml")
        return {item["id"]: item.get("policy") == "locked" for item in registry.get("servers", [])}
    root = repository / kind
    found: dict[str, bool] = {}
    if not root.exists():
        return found
    candidates = root.iterdir() if kind == "skills" else root.glob("*.md")
    for path in candidates:
        metadata: dict[str, Any] = {}
        identifier = path.stem
        if path.is_dir() and (path / "SKILL.md").is_file():
            metadata = markdown_frontmatter(path / "SKILL.md")
            identifier = str(metadata.get("id", path.name))
        elif path.suffix == ".md":
            metadata = markdown_frontmatter(path)
            identifier = str(metadata.get("id", path.stem))
        found[identifier] = metadata.get("policy") == "enforced" or (kind == "rules" and identifier in {"security", "context", "models"})
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
                elif mode == "disable" and core[target]:
                    result.error("overrides", f"{path}: нельзя отключить enforced {kind[:-1]} {target!r}")
    if result.ok:
        result.info("overrides", f"Local overrides валидны; проверено: {checked}")
    return result
