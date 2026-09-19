from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml


def write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def make_model_repository(tmp_path: Path, real_repository: Path, corporate_models: list[dict], local_models: list[dict] | None = None) -> Path:
    repository = tmp_path / "kit"
    for directory in ("models/schemas", "agents", "skills", "rules", "clients", "mcp", "templates"):
        (repository / directory).mkdir(parents=True, exist_ok=True)
    shutil.copy(real_repository / "models/schemas/models.schema.json", repository / "models/schemas/models.schema.json")
    providers = [{"id": item} for item in ("openai", "anthropic", "ollama", "custom")]
    write_yaml(repository / "models/corporate.yaml", {"version": 1, "providers": providers, "models": corporate_models})
    if local_models is not None:
        write_yaml(repository / "models/user.local.yaml", {"version": 1, "providers": providers, "models": local_models})
    return repository


def model(identifier: str, provider: str = "openai") -> dict:
    return {"id": identifier, "provider": provider, "capabilities": {"coding": True, "tool_use": True}}
