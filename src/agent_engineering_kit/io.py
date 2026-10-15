"""Безопасное чтение и атомарная запись данных."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .errors import AgentKitError


def load_yaml(path: Path, *, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise AgentKitError(f"Файл не найден: {path}")
        return {}
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise AgentKitError(f"Некорректный YAML {path}: {error}") from error
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AgentKitError(f"Корень YAML должен быть объектом: {path}")
    return value


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AgentKitError(f"Некорректный JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise AgentKitError(f"Корень JSON должен быть объектом: {path}")
    return value


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def markdown_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        raise AgentKitError(f"Не закрыт YAML front matter: {path}")
    try:
        value = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as error:
        raise AgentKitError(f"Некорректный front matter {path}: {error}") from error
    if not isinstance(value, dict):
        raise AgentKitError(f"Front matter должен быть объектом: {path}")
    return value
