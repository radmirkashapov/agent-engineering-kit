"""Классификация итоговой политики и происхождение её значений."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from .conventions import load_conventions
from .errors import AgentKitError
from .io import load_yaml
from .paths import KitPaths
from .projects import LogicalProject
from .result import ValidationResult
from .schema import validate_instance


CLASSIFICATIONS = {"preference", "restriction", "invariant"}
_ENUM_DOMAINS = {
    "client.preferred": {"auto", "codex", "claude-code", "claude-desktop", "opencode", "cline"},
    "approvals.profile": {"readonly", "autonomous", "custom"},
    "sandbox.mode": {"client-native", "read-only", "workspace-write", "unrestricted"},
    "network.mode": {"deny", "allowlist", "unrestricted"},
    "mcp.access_profile": {"readonly", "editor", "administrator"},
}
TECHNICAL_INVARIANTS = (
    {"key": "secrets.in_git", "value": False, "classification": "invariant"},
    {"key": "conventions.override", "value": False, "classification": "invariant"},
    {"key": "policy.invariants_override", "value": False, "classification": "invariant"},
)


@dataclass
class PolicyResolution:
    values: dict[str, Any] = field(default_factory=dict)
    classifications: dict[str, str] = field(default_factory=dict)
    provenance: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "values": self.values,
            "classifications": self.classifications,
            "provenance": self.provenance,
            "warnings": self.warnings,
        }


def _validate_policy_value(key: str, value: Any) -> None:
    if key in _ENUM_DOMAINS and value not in _ENUM_DOMAINS[key]:
        raise AgentKitError(f"Недопустимое значение политики {key}: {value!r}")
    if key in {"models.allowed", "tools.allowed"} and (
        not isinstance(value, list) or not all(isinstance(item, str) and item for item in value)
    ):
        raise AgentKitError(f"Значение политики {key} должно быть массивом непустых строк")
    if key in {"secrets.in_git", "conventions.override", "policy.invariants_override"} and not isinstance(value, bool):
        raise AgentKitError(f"Значение политики {key} должно быть логическим")


def resolve_policy(
    layers: list[dict[str, Any]],
    overrides: list[dict[str, Any]] | None = None,
    *,
    final_layers: list[dict[str, Any]] | None = None,
) -> PolicyResolution:
    """Resolve baseline, local overrides, and unoverrideable final layers."""
    result = PolicyResolution()
    for layer in layers:
        source = layer["source"]
        for entry in layer["entries"]:
            key = entry["key"]
            classification = entry["classification"]
            value = entry["value"]
            _validate_policy_value(key, value)
            if classification not in CLASSIFICATIONS:
                raise AgentKitError(f"Неизвестный класс политики {classification!r}: {key}")
            previous = result.classifications.get(key)
            if previous == "invariant" and (value != result.values[key] or classification != "invariant"):
                raise AgentKitError(f"Нельзя изменить инвариант политики: {key}")
            if previous == "restriction" and classification == "preference":
                raise AgentKitError(f"Нельзя ослабить restriction до preference: {key}")
            result.values[key] = value
            result.classifications[key] = classification
            result.provenance.setdefault(key, []).append({
                "source": source,
                "classification": classification,
                "value": value,
                "reason": None,
                "decision": "set",
            })
    final_keys = {entry["key"] for layer in final_layers or [] for entry in layer["entries"]}
    for override in overrides or []:
        key = override["key"]
        if key in final_keys:
            raise AgentKitError(f"Нельзя переопределить инвариант политики: {key}")
        if key not in result.values:
            raise AgentKitError(f"Неизвестный ключ локального override: {key}")
        reason = override.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise AgentKitError(f"Для локального override обязательна причина (reason): {key}")
        classification = result.classifications[key]
        if classification == "invariant":
            raise AgentKitError(f"Нельзя переопределить инвариант политики: {key}")
        value = override["value"]
        _validate_policy_value(key, value)
        decision = "override-restriction" if classification == "restriction" and value != result.values[key] else "override-preference"
        if decision == "override-restriction":
            result.warnings.append(f"Локальное переопределение restriction {key}: {reason}")
        result.values[key] = value
        result.provenance[key].append({
            "source": override.get("source", "user-local"),
            "classification": classification,
            "value": value,
            "reason": reason,
            "decision": decision,
        })
    for layer in final_layers or []:
        source = layer["source"]
        for entry in layer["entries"]:
            key = entry["key"]
            classification = entry["classification"]
            if classification != "invariant":
                raise AgentKitError(f"Финальный слой допускает только инварианты: {key}")
            _validate_policy_value(key, entry["value"])
            result.values[key] = entry["value"]
            result.classifications[key] = classification
            result.provenance.setdefault(key, []).append({
                "source": source,
                "classification": classification,
                "value": entry["value"],
                "reason": None,
                "decision": "set",
            })
    return result


def load_policy_overrides(repository: Path, paths: KitPaths, project_id: str | None = None) -> list[dict[str, Any]]:
    if project_id is not None and not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", project_id):
        raise AgentKitError(f"Некорректный project ID для policy overrides: {project_id!r}")
    roots = [("user-global", paths.overrides / "global")]
    if project_id:
        roots.append(("user-project", paths.overrides / "projects" / project_id))
    collected: list[dict[str, Any]] = []
    for source, root in roots:
        for path in sorted((root / "policy").glob("*.yaml")):
            document = load_yaml(path)
            validation = validate_instance(document, repository / "schemas" / "policy-override.schema.json", str(path))
            if not validation.ok:
                failures = "; ".join(item.message for item in validation.diagnostics)
                raise AgentKitError(f"Некорректный policy override: {failures}")
            for entry in document["overrides"]:
                if not entry["reason"].strip():
                    raise AgentKitError(f"Для локального override обязательна причина (reason): {path}")
                collected.append({**entry, "source": source})
    return collected


def effective_policy(repository: Path, paths: KitPaths, project: LogicalProject | None = None, *, include_local: bool = True) -> PolicyResolution:
    """Собрать исходную политику возможностей из доступных версионируемых данных."""
    layers: list[dict[str, Any]] = [{
        "source": "kit",
        "entries": [
            {"key": "client.preferred", "value": "auto", "classification": "preference"},
            {"key": "approvals.profile", "value": "readonly", "classification": "restriction"},
            {"key": "sandbox.mode", "value": "client-native", "classification": "restriction"},
            {"key": "network.mode", "value": "deny", "classification": "restriction"},
            {"key": "tools.allowed", "value": ["read", "search"], "classification": "restriction"},
            {"key": "mcp.access_profile", "value": "readonly", "classification": "restriction"},
        ],
    }]
    corporate = load_yaml(repository / "models" / "corporate.yaml")
    allowed = [item["id"] for item in corporate.get("models", [])]
    if allowed:
        layers.append({
            "source": "corporate:models/corporate.yaml",
            "entries": [{"key": "models.allowed", "value": allowed, "classification": "restriction"}],
        })
    if project and isinstance(project.manifest.get("harness"), dict):
        preferred = project.manifest["harness"].get("preferred_client")
        if preferred:
            layers.append({
                "source": f"project:{project.identifier}",
                "entries": [{"key": "client.preferred", "value": preferred, "classification": "preference"}],
            })
    conventions = load_conventions(repository, project)
    final_layers = [
        {
            "source": item["source"],
            "entries": [{"key": f"conventions.{item['id']}", "value": True, "classification": "invariant"}],
        }
        for item in conventions
    ]
    final_layers.append({"source": "technical-invariants", "entries": list(TECHNICAL_INVARIANTS)})
    overrides = load_policy_overrides(repository, paths, project.identifier if project else None) if include_local else []
    return resolve_policy(layers, overrides, final_layers=final_layers)


def validate_policy(repository: Path, paths: KitPaths, project: LogicalProject | None = None, *, include_local: bool = True) -> ValidationResult:
    result = ValidationResult()
    try:
        effective = effective_policy(repository, paths, project, include_local=include_local)
    except (AgentKitError, OSError, KeyError) as error:
        result.error("policy", str(error))
        return result
    for warning in effective.warnings:
        result.warning("policy", warning)
    result.info("policy", "Effective policy валидна")
    return result
