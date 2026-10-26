"""Единая точка запуска всех проверок конфигурации."""

from __future__ import annotations

from pathlib import Path

from .clients import validate_clients
from .conventions import validate_conventions
from .definitions import validate_agents, validate_locks, validate_mcp, validate_skills
from .git_hygiene import validate_git_hygiene
from .models import validate_models
from .overrides import validate_overrides
from .paths import KitPaths
from .profiles import validate_profiles
from .policy import validate_policy
from .project_skills import ProjectSkillRepositoryManager, redact_url
from .projects import LogicalProject, find_project
from .result import ValidationResult
from .schema import validate_instance, validate_repository_schemas
from .security import validate_security


def validate_project_skills(
    repository: Path, paths: KitPaths, project: LogicalProject | None, *, include_local: bool = True,
) -> ValidationResult:
    """Офлайн-проверка явного project context; remote разрешается только resync."""
    result = ValidationResult()
    try:
        if project is None:
            result.info("project-skills", "Logical project не найден; источник project-skills не настроен")
            return result
        schema = validate_instance(project.manifest, repository / "schemas/project.schema.json", "logical project")
        for item in schema.diagnostics:
            result.add(item.severity, "project-skills", redact_url(item.message))
        if not result.ok:
            return result
        observed = ProjectSkillRepositoryManager(repository, paths, project).inspect(ci=not include_local)
        if observed["source_url"] is None:
            result.info("project-skills", "Источник project-skills не настроен")
            return result
        result.info("project-skills", f"Источник manifest: {observed['source_url']}; "
                    f"default branch: {observed['default_branch']}; выбранная ветка: {observed['requested_branch']}")
        revision = observed["active_revision"]
        result.info("project-skills", f"Активная проверенная ревизия: {revision}" if revision else
                    "Активная проверенная ревизия отсутствует")
        result.info("project-skills", "Удалённая ветка не разрешена: проверка не выполняет fetch; "
                    "активный SHA не подтверждает текущую ревизию default branch")
    except Exception as error:
        result.error("project-skills", redact_url(str(error)))
    return result


VALIDATORS = {
    "schemas": lambda repository, paths, include_local: validate_repository_schemas(repository),
    "models": lambda repository, paths, include_local: validate_models(repository, include_local=include_local, local_path=paths.overrides / "models.yaml"),
    "agents": lambda repository, paths, include_local: validate_agents(repository),
    "skills": lambda repository, paths, include_local: validate_skills(repository),
    "project-skills": lambda repository, paths, include_local: validate_project_skills(
        repository, paths, find_project(Path.cwd()), include_local=include_local),
    "mcp": lambda repository, paths, include_local: validate_mcp(repository),
    "catalogs": lambda repository, paths, include_local: validate_locks(repository),
    "clients": lambda repository, paths, include_local: validate_clients(repository),
    "profiles": lambda repository, paths, include_local: validate_profiles(repository),
    "conventions": lambda repository, paths, include_local: validate_conventions(repository, find_project(Path.cwd()) if include_local else None),
    "policy": lambda repository, paths, include_local: validate_policy(repository, paths, find_project(Path.cwd()) if include_local else None, include_local=include_local),
    "overrides": lambda repository, paths, include_local: validate_overrides(repository, paths.overrides) if include_local else ValidationResult(),
    "git-hygiene": lambda repository, paths, include_local: validate_git_hygiene(repository, paths, require_gitleaks=not include_local),
    "security": lambda repository, paths, include_local: validate_security(repository),
}


def validate(repository: Path, paths: KitPaths, target: str = "all", *, include_local: bool = True) -> ValidationResult:
    result = ValidationResult()
    names = VALIDATORS if target == "all" else {target: VALIDATORS[target]}
    for validator in names.values():
        try:
            for item in validator(repository, paths, include_local).diagnostics:
                result.add(item.severity, item.check, redact_url(item.message))
        except Exception as error:
            result.error(target if target != "all" else "validation", redact_url(str(error)))
    if not include_local:
        result.info("validation", "CI baseline: user-local overrides отключены")
    return result
