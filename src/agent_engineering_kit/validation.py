"""Aggregating validation entry point."""

from __future__ import annotations

from pathlib import Path

from .clients import validate_clients
from .definitions import validate_agents, validate_mcp, validate_skills
from .git_hygiene import validate_git_hygiene
from .models import validate_models
from .overrides import validate_overrides
from .paths import KitPaths
from .result import ValidationResult
from .schema import validate_repository_schemas
from .security import validate_security


VALIDATORS = {
    "schemas": lambda repository, paths, include_local: validate_repository_schemas(repository),
    "models": lambda repository, paths, include_local: validate_models(repository, include_local=include_local),
    "agents": lambda repository, paths, include_local: validate_agents(repository),
    "skills": lambda repository, paths, include_local: validate_skills(repository),
    "mcp": lambda repository, paths, include_local: validate_mcp(repository),
    "clients": lambda repository, paths, include_local: validate_clients(repository),
    "overrides": lambda repository, paths, include_local: validate_overrides(repository, paths.overrides) if include_local else ValidationResult(),
    "git-hygiene": lambda repository, paths, include_local: validate_git_hygiene(repository),
    "security": lambda repository, paths, include_local: validate_security(repository),
}


def validate(repository: Path, paths: KitPaths, target: str = "all", *, include_local: bool = True) -> ValidationResult:
    result = ValidationResult()
    names = VALIDATORS if target == "all" else {target: VALIDATORS[target]}
    for validator in names.values():
        try:
            result.extend(validator(repository, paths, include_local))
        except Exception as error:
            result.error(target if target != "all" else "validation", str(error))
    if not include_local:
        result.info("validation", "CI baseline: user-local overrides отключены")
    return result
