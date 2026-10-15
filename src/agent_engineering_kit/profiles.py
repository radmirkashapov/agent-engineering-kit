"""Общие профили разработчиков, тестировщиков и рецензентов."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import AgentKitError
from .io import load_yaml
from .result import ValidationResult
from .schema import validate_instance


EXPECTED_PROFILES = frozenset({"developer", "tester", "reviewer"})


def load_profiles(repository: Path) -> list[dict[str, Any]]:
    """Загрузить профили в стабильном порядке."""
    profiles = [load_yaml(path) for path in sorted((repository / "profiles").glob("*.yaml"))]
    identifiers = [item.get("id") for item in profiles]
    if len(identifiers) != len(set(identifiers)):
        raise AgentKitError("Обнаружены повторяющиеся ID профилей")
    return profiles


def validate_profiles(repository: Path) -> ValidationResult:
    result = ValidationResult()
    profiles = load_profiles(repository)
    schema = repository / "schemas" / "profile.schema.json"
    for path, profile in zip(sorted((repository / "profiles").glob("*.yaml")), profiles, strict=True):
        result.extend(validate_instance(profile, schema, str(path)))
        description = profile.get("description")
        if isinstance(description, str) and not description.isascii():
            result.error("profiles", f"Описание профиля должно быть на английском: {path}")
    actual = {str(item.get("id")) for item in profiles}
    if actual != EXPECTED_PROFILES:
        result.error("profiles", f"Ожидаются профили {sorted(EXPECTED_PROFILES)}, получено {sorted(actual)}")
    if result.ok:
        result.info("profiles", f"Профили валидны: {len(profiles)}")
    return result


def compile_permission_profile(
    repository: Path,
    profile_id: str,
    *,
    client_capabilities: set[str],
) -> dict[str, Any]:
    """Сопоставить независимую политику с реально доступными средствами клиента."""
    profile = next((item for item in load_profiles(repository) if item.get("id") == profile_id), None)
    if profile is None:
        raise AgentKitError(f"Неизвестный профиль: {profile_id}")
    controls = ("approvals", "sandbox", "network", "tools")
    return {
        "profile": profile_id,
        "permissions": profile["permissions"],
        "enforcement": {
            control: "client" if control in client_capabilities else "unavailable"
            for control in controls
        },
    }
