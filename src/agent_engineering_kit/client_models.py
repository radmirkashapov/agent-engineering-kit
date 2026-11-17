"""Безопасная публикация модели и endpoint без управления секретами."""

from __future__ import annotations

import json
import os
import platform
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .errors import AgentKitError
from .io import atomic_write, load_json, load_yaml
from .models import load_policy, validate_models
from .paths import KitPaths, ensure_runtime


CLIENT_MODEL_CAPABILITIES: dict[str, dict[str, str]] = {
    "codex": {
        "mode": "managed",
        "path": "~/.codex/config.toml",
        "credentials": "Codex reads the API key from env_key; Kit preserves an existing env_key.",
    },
    "opencode": {
        "mode": "managed",
        "path": "~/.config/opencode/opencode.json",
        "credentials": "OpenCode reads env or settings.apiKey; Kit preserves both fields.",
    },
    "cline": {
        "mode": "manual",
        "path": "Cline provider storage",
        "credentials": "Cline owns provider profiles and secret storage; configure it in Cline or cline auth.",
    },
    "claude-code": {
        "mode": "manual",
        "path": "Claude Code settings and environment",
        "credentials": "Claude Code uses its own authentication and Anthropic-compatible transport.",
    },
    "claude-desktop": {
        "mode": "unsupported",
        "path": "Claude Desktop account settings",
        "credentials": "Claude Desktop has no managed OpenAI-compatible provider contract.",
    },
}


def _local_document(repository: Path, paths: KitPaths) -> dict[str, Any]:
    preferred = paths.overrides / "models.yaml"
    if preferred.is_file():
        return load_yaml(preferred)
    fallback = repository / "models" / "user.local.yaml"
    return load_yaml(fallback) if fallback.is_file() else {}


def model_catalog(repository: Path, paths: KitPaths) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Вернуть effective providers и модели, пригодные для client registration."""
    corporate = load_yaml(repository / "models" / "corporate.yaml")
    local = _local_document(repository, paths)
    policy = load_policy(repository, local_path=paths.overrides / "models.yaml")
    providers: dict[str, dict[str, Any]] = {}
    for document in (corporate, local):
        for item in document.get("providers", []) or []:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                providers[item["id"]] = dict(item)
    effective = {**policy.corporate, **policy.local}
    models: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in effective.values():
        provider = item.get("provider")
        if isinstance(provider, str) and provider in providers:
            models[provider].append(dict(item))
    return providers, {identifier: sorted(values, key=lambda item: item["id"]) for identifier, values in models.items()}


def list_client_models(repository: Path, paths: KitPaths) -> list[dict[str, Any]]:
    providers, models = model_catalog(repository, paths)
    return [
        {**provider, "models": models.get(identifier, [])}
        for identifier, provider in sorted(providers.items())
    ]


def client_model_status(repository: Path, paths: KitPaths) -> dict[str, dict[str, Any]]:
    providers, models = model_catalog(repository, paths)
    result: dict[str, dict[str, Any]] = {}
    for client, capability in CLIENT_MODEL_CAPABILITIES.items():
        result[client] = {
            **capability,
            "providers": sorted(identifier for identifier in models if providers[identifier].get("base_url")),
        }
    return result


def _state_path(paths: KitPaths) -> Path:
    return paths.state / "client-models.json"


def _load_state(paths: KitPaths) -> dict[str, Any]:
    path = _state_path(paths)
    if not path.is_file():
        return {"codex": [], "opencode": [], "opencode_config": None}
    document = load_json(path)
    return {
        "codex": [item for item in document.get("codex", []) if isinstance(item, str)],
        "opencode": [item for item in document.get("opencode", []) if isinstance(item, str)],
        "opencode_config": document.get("opencode_config") if isinstance(document.get("opencode_config"), str) else None,
    }


def _write_state(paths: KitPaths, state: dict[str, Any]) -> None:
    atomic_write(_state_path(paths), json.dumps({"version": 1, **state}, ensure_ascii=False, indent=2) + "\n")


def _toml_value(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _codex_block(provider: dict[str, Any]) -> str:
    identifier = provider["id"]
    lines = [
        f"# agent-kit:model-provider:{identifier}:start",
        f"[model_providers.{identifier}]",
        f"name = {_toml_value(str(provider.get('name') or identifier))}",
        f"base_url = {_toml_value(str(provider['base_url']))}",
    ]
    if provider.get("api_key_env"):
        lines.append(f"env_key = {_toml_value(str(provider['api_key_env']))}")
    lines.append(f"wire_api = {_toml_value(str(provider.get('wire_api') or 'responses'))}")
    lines.append(f"# agent-kit:model-provider:{identifier}:end")
    return "\n".join(lines) + "\n"


def _preserved_codex_env_key(block: str) -> str | None:
    match = re.search(
        r"^env_key\s*=\s*(?:\"(?P<double>(?:\\.|[^\"\\])*)\"|'(?P<single>[^']*)')\s*(?:#.*)?$",
        block,
        flags=re.MULTILINE,
    )
    if match is None:
        return None
    if match.group("double") is not None:
        return json.loads(f'"{match.group("double")}"')
    return match.group("single")


def _sync_codex(providers: Iterable[dict[str, Any]], paths: KitPaths, home: Path) -> dict[str, Any]:
    config_path = home / ".codex" / "config.toml"
    content = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    state = _load_state(paths)
    owned = set(state["codex"])
    changed = False
    synchronized: list[str] = []
    for provider in providers:
        identifier = provider["id"]
        marker = re.escape(f"# agent-kit:model-provider:{identifier}:start")
        end = re.escape(f"# agent-kit:model-provider:{identifier}:end")
        existing = re.search(marker + r"\n.*?" + end + r"\n?", content, flags=re.DOTALL)
        table = re.search(r"^\[model_providers\." + re.escape(identifier) + r"\]\s*$", content, flags=re.MULTILINE)
        # Одного state недостаточно: пользователь мог удалить managed-блок
        # и использовать table для иной конфигурации provider.
        if table and not existing:
            raise AgentKitError(f"Codex model provider ownership collision: {identifier}")
        rendered_provider = dict(provider)
        if existing:
            if env_key := _preserved_codex_env_key(existing.group(0)):
                rendered_provider["api_key_env"] = env_key
        block = _codex_block(rendered_provider)
        if existing:
            updated = content[:existing.start()] + block + content[existing.end():]
        else:
            updated = content + ("\n" if content and not content.endswith("\n\n") else "") + block
        if updated != content:
            content = updated
            changed = True
        owned.add(identifier)
        synchronized.append(identifier)
    if changed:
        atomic_write(config_path, content)
    state["codex"] = sorted(owned)
    _write_state(paths, state)
    return {"status": "SYNCED", "path": str(config_path), "providers": synchronized, "changed": changed}


def _opencode_models(models: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in models:
        value: dict[str, Any] = {"name": item.get("name") or item["id"]}
        if item.get("model_id"):
            value["modelID"] = item["model_id"]
        limit = {key: item[source] for key, source in (("context", "context_window"), ("output", "max_output_tokens")) if item.get(source)}
        if limit:
            value["limit"] = limit
        result[item["id"]] = value
    return result


def _opencode_document(providers: Iterable[dict[str, Any]], models: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Собрать конфиг без literal credentials и без пользовательских полей."""
    provider_map: dict[str, Any] = {}
    for provider in providers:
        identifier = provider["id"]
        entry: dict[str, Any] = {
            "name": provider.get("name") or identifier,
            "package": "@opencode/ai/providers/openai-compatible",
            "settings": {"baseURL": provider["base_url"]},
            "models": _opencode_models(models.get(identifier, [])),
        }
        if provider.get("api_key_env"):
            entry["env"] = [provider["api_key_env"]]
        provider_map[identifier] = entry
    return {"$schema": "https://opencode.ai/config.json", "providers": provider_map}


def opencode_managed_config_path(environ: dict[str, str] | None = None) -> Path:
    """Вернуть официальный system-level config OpenCode, а не user config."""
    env = os.environ if environ is None else environ
    if configured := env.get("AGENT_KIT_OPENCODE_MANAGED_CONFIG"):
        return Path(configured).expanduser()
    if platform.system() == "Darwin":
        return Path("/Library/Application Support/opencode/opencode.json")
    if platform.system() == "Windows":
        return Path(env.get("ProgramData", r"C:\\ProgramData")) / "opencode" / "opencode.json"
    return Path("/etc/opencode/opencode.json")


def _sync_opencode(providers: Iterable[dict[str, Any]], models: dict[str, list[dict[str, Any]]], paths: KitPaths, home: Path) -> dict[str, Any]:
    config_path = opencode_managed_config_path()
    state = _load_state(paths)
    owner = state.get("opencode_config")
    if config_path.exists() and owner != str(config_path):
        return {"status": "CONFIG_REQUIRED", "path": str(config_path), "changed": False,
                "reason": "OpenCode system configuration is not owned by Agent Kit"}
    document = _opencode_document(providers, models)
    serialized = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    try:
        atomic_write(config_path, serialized)
    except OSError:
        return {"status": "CONFIG_REQUIRED", "path": str(config_path), "changed": False,
                "reason": "Agent Kit needs permission to write the OpenCode system configuration"}
    state["opencode"] = sorted(provider["id"] for provider in providers)
    state["opencode_config"] = str(config_path)
    _write_state(paths, state)
    return {"status": "SYNCED", "path": str(config_path), "providers": state["opencode"], "changed": True}


def sync_client_models(
    repository: Path, paths: KitPaths, *, home: Path | None = None, clients: Iterable[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Синхронизировать только безопасно управляемые client model contracts."""
    ensure_runtime(paths)
    validation = validate_models(repository, include_local=True, local_path=paths.overrides / "models.yaml")
    if not validation.ok:
        messages = "; ".join(item.message for item in validation.diagnostics if item.severity == "ERROR")
        raise AgentKitError(f"Некорректный local model catalog: {messages}")
    selected = tuple(clients or CLIENT_MODEL_CAPABILITIES)
    unknown = sorted(set(selected) - set(CLIENT_MODEL_CAPABILITIES))
    if unknown:
        raise AgentKitError(f"Неизвестный client model adapter: {', '.join(unknown)}")
    user_home = home or Path.home()
    providers, models = model_catalog(repository, paths)
    compatible = [provider for identifier, provider in providers.items() if provider.get("base_url") and identifier in models]
    result: dict[str, dict[str, Any]] = {}
    for client in selected:
        mode = CLIENT_MODEL_CAPABILITIES[client]["mode"]
        if mode == "managed":
            result[client] = (
                _sync_codex(compatible, paths, user_home)
                if client == "codex"
                else _sync_opencode(compatible, models, paths, user_home)
            )
        else:
            result[client] = {"status": mode.upper(), **CLIENT_MODEL_CAPABILITIES[client], "changed": False}
    return result
