"""Проверка структурированных метаданных ролей, skills и MCP."""

from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlsplit
import unicodedata

from .io import load_yaml, markdown_frontmatter
from .result import ValidationResult
from .schema import validate_instance


DEFAULT_AGENT_IDS = frozenset({"orchestrator", "architect", "developer", "reviewer", "qa-engineer"})
_ENGLISH_MARKERS = frozenset({"an", "and", "before", "for", "from", "into", "of", "on", "or", "the", "to", "with", "without"})
_ENGLISH_ACTION_VERBS = frozenset({
    "access", "analyze", "assess", "automate", "build", "coordinate", "design",
    "diagnose", "greet", "identify", "implement", "initialize", "inspect", "maintain",
    "navigate", "prove", "retrieve", "review", "use", "verify",
})


def is_english_text(value: object) -> bool:
    """Эвристически проверить содержательную английскую прозу в переносимом описании."""
    if not isinstance(value, str):
        return False
    letters = [character for character in value if character.isalpha()]
    if len(letters) < 12:
        return False
    if any("LATIN" not in unicodedata.name(character, "") for character in letters):
        return False
    words = [word.lower() for word in re.findall(r"[A-Za-z]+", value)]
    marker_count = sum(word in _ENGLISH_MARKERS for word in words)
    starts_with_action = bool(words) and words[0] in _ENGLISH_ACTION_VERBS
    return len(words) >= 4 and (marker_count >= 2 or starts_with_action and marker_count >= 1)


def url_contains_credentials(url: str) -> bool:
    """Отклонить URL с userinfo, query или fragment в версионируемой конфигурации."""
    parsed = urlsplit(url)
    return bool(parsed.username or parsed.password or parsed.query or parsed.fragment)


def _validate_english_description(result: ValidationResult, section: str, identifier: object, value: object) -> None:
    """Проверить переносимое английское описание базового компонента."""
    if not is_english_text(value):
        result.error(section, f"{identifier}: default description должен быть на английском")


def validate_skill_directory(path: Path, schema: Path, identifier: str, label: str) -> ValidationResult:
    """Проверить локальный каталог skill и совпадение его переносимого идентификатора."""
    result = ValidationResult()
    skill_file = path / "SKILL.md"
    if not path.is_dir() or not skill_file.is_file():
        result.error("skills", f"{label}: ожидается существующий каталог с SKILL.md: {path}")
        return result
    try:
        metadata = markdown_frontmatter(skill_file)
    except Exception as error:
        result.error("skills", f"{label}: не удалось прочитать SKILL.md: {error}")
        return result
    result.extend(validate_instance(metadata, schema, str(skill_file)))
    actual = metadata.get("name") or metadata.get("id")
    if actual != identifier:
        result.error("skills", f"{label}: skill name {actual!r} должен совпадать с target {identifier!r}")
    return result


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
        _validate_english_description(result, "agents", identifier, metadata.get("role"))
        content = path.read_text(encoding="utf-8")
        if not is_english_text(content):
            result.error("agents", f"{identifier}: default role definition должен быть на английском")
        if len(content.splitlines()) < 45:
            result.error("agents", f"{identifier}: role definition недостаточно подробный")
    missing = sorted(DEFAULT_AGENT_IDS - identifiers)
    unexpected = sorted(identifiers - DEFAULT_AGENT_IDS)
    if missing:
        result.error("agents", f"Отсутствуют обязательные agent roles: {missing}")
    if unexpected:
        result.error("agents", f"Неизвестные default agent roles: {unexpected}")
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
        _validate_english_description(result, "skills", identifier, metadata.get("description"))
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
        _validate_english_description(result, "mcp", identifier, server.get("description"))
        for name, source in (server.get("environment") or {}).items():
            if not isinstance(source, str) or not source.startswith("env:"):
                result.error("mcp", f"MCP {identifier}: environment.{name} должен использовать env:VARIABLE")
            elif source.removeprefix("env:") not in example_variables:
                result.error("mcp", f"MCP {identifier}: {source} отсутствует в .env.example")
        environment_names = set((server.get("environment") or {}).keys())
        for name in server.get("required_environment", []) or []:
            if name not in environment_names:
                result.error("mcp", f"MCP {identifier}: required_environment {name} отсутствует в environment")
        image = (server.get("installation") or {}).get("image")
        if image and not re.search(r"@sha256:[0-9a-f]{64}$", image):
            result.error("mcp", f"MCP {identifier}: container image должен быть закреплён immutable digest")
        for field, url in (
            ("source.repository", (server.get("source") or {}).get("repository")),
            ("installation.endpoint", (server.get("installation") or {}).get("endpoint")),
        ):
            if not isinstance(url, str):
                continue
            if url_contains_credentials(url):
                result.error("mcp", f"MCP {identifier}: credentials запрещены в {field} URL")
    corporate_path = repository / "catalog" / "corporate" / "mcp.yaml"
    if corporate_path.is_file():
        corporate = load_yaml(corporate_path)
        result.extend(validate_instance(corporate, repository / "schemas" / "mcp.schema.json", str(corporate_path)))
        classes_path = corporate_path.with_name("data-classification.yaml")
        profiles_path = corporate_path.with_name("access-profiles.yaml")
        classes = load_yaml(classes_path) if classes_path.is_file() else {}
        profiles = load_yaml(profiles_path) if profiles_path.is_file() else {}
        known_classes = {entry.get("id") for entry in classes.get("classes", [])}
        if classes.get("version") != 1 or known_classes != {"public", "internal", "confidential", "restricted"}:
            result.error("mcp", "Corporate data classification неполна или имеет неверную версию")
        for data_class in classes.get("classes", []):
            if data_class.get("logging") not in {"redacted", "metadata-only"}:
                result.error("mcp", f"Corporate data class {data_class.get('id')}: logging должен быть redacted или metadata-only")
            if data_class.get("model_access") not in {"approved-only", "local-only", "denied"}:
                result.error("mcp", f"Corporate data class {data_class.get('id')}: неверный model_access")
            if data_class.get("id") == "restricted" and data_class.get("model_access") != "denied":
                result.error("mcp", "Corporate data class restricted: доступ модели должен быть denied")
        profile_ids: set[str] = set()
        for profile in profiles.get("profiles", []):
            profile_id = profile.get("id")
            modes = profile.get("allowed_modes")
            invalid_modes = (
                not isinstance(modes, list)
                or not modes
                or any(not isinstance(mode, str) or mode not in {"read", "write", "admin"} for mode in modes)
            )
            if profile_id in profile_ids or invalid_modes or (profile_id == "readonly" and modes != ["read"]):
                result.error("mcp", f"Corporate access profile {profile_id}: некорректные режимы или повторяющийся ID")
            profile_ids.add(profile_id)
        if profiles.get("version") != 1 or "readonly" not in profile_ids:
            result.error("mcp", "Corporate access profile readonly отсутствует или имеет неверную версию")
        registry_by_id = {entry.get("id"): entry for entry in document.get("servers", [])}
        corporate_ids = {entry.get("id") for entry in corporate.get("servers", [])}
        for identifier in sorted(identifiers - corporate_ids):
            result.error("mcp", f"MCP {identifier}: не имеет capability policy")
        seen_capabilities: set[str] = set()
        for entry in corporate.get("servers", []):
            identifier = entry.get("id")
            if identifier not in identifiers:
                result.error("mcp", f"Corporate MCP {identifier}: отсутствует в registry")
            endpoint = (registry_by_id.get(identifier, {}).get("installation") or {}).get("endpoint")
            if endpoint and urlsplit(endpoint).hostname not in (entry.get("boundaries") or {}).get("allowed_hosts", []):
                result.error("mcp", f"Corporate MCP {identifier}: endpoint host отсутствует в allowed_hosts")
            if not set(entry.get("data_classes", [])) <= known_classes:
                result.error("mcp", f"Corporate MCP {identifier}: неизвестный класс данных")
            capabilities = entry.get("capabilities", [])
            if (entry.get("boundaries") or {}).get("read_only") and any(
                capability.get("mode") != "read" for capability in capabilities
            ):
                result.error("mcp", f"Corporate MCP {identifier}: read_only несовместим с write/admin capability")
            for capability in capabilities:
                name = capability.get("id")
                if name in seen_capabilities:
                    result.error("mcp", f"Повторяющаяся corporate capability: {name}")
                seen_capabilities.add(name)
                if not set(capability.get("data_classes", [])) <= set(entry.get("data_classes", [])):
                    result.error("mcp", f"Corporate capability {name}: data class выходит за границы MCP")
        for entry in corporate.get("servers", []):
            for capability in entry.get("capabilities", []):
                for conflict in capability.get("conflicts_with", []):
                    if conflict not in seen_capabilities:
                        result.error("mcp", f"Corporate capability {capability.get('id')}: неизвестный конфликт {conflict}")
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
