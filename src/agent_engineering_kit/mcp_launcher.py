"""Контракты запуска stdio MCP без сохранения значений credentials."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .errors import AgentKitError
from .io import atomic_write
from .mcp_credentials import McpCredentialStore
from .paths import KitPaths, resolve_paths


@dataclass(frozen=True)
class McpLaunchContract:
    version: int
    mcp_id: str
    command: str
    args: tuple[str, ...]
    environment: dict[str, str]
    required_environment: tuple[str, ...]
    data_home: str | None = None


def _safe_identifier(value: object) -> bool:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) is None:
        return False
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)}
    return not value.endswith(".") and value.split(".")[0].upper() not in reserved


def _environment_name(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is not None


def _arguments_valid(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(arg, str) and "\x00" not in arg for arg in value)


def _canonical_data_home(value: object) -> bool:
    if not isinstance(value, str) or "\x00" in value or not value:
        return False
    try:
        path = Path(value)
        return path.is_absolute() and str(path.resolve()) == value
    except (OSError, ValueError):
        return False


def write_launch_contract(paths: KitPaths, item: dict[str, Any], executable: Path) -> Path:
    identifier = item.get("id")
    if not _safe_identifier(identifier):
        raise AgentKitError("Некорректный идентификатор MCP для контракта запуска")
    environment = item.get("environment", {})
    if not isinstance(environment, dict) or any(
        not _environment_name(target)
        or not isinstance(reference, str)
        or not reference.startswith("env:")
        or not _environment_name(reference[4:])
        for target, reference in environment.items()
    ):
        raise AgentKitError(f"Некорректные ссылки окружения MCP {identifier}")
    args = item.get("args", [])
    required = item.get("required_environment", [])
    if not _arguments_valid(args) or not isinstance(required, list) or not all(_environment_name(name) for name in required):
        raise AgentKitError(f"Некорректные поля контракта запуска MCP {identifier}")
    try:
        command = str(executable.resolve())
        data_home = str(paths.data.resolve())
    except (OSError, ValueError):
        raise AgentKitError(f"Некорректный исполняемый файл MCP {identifier}") from None
    contract = McpLaunchContract(
        version=2,
        mcp_id=identifier,
        command=command,
        args=tuple(args),
        environment={target: reference[4:] for target, reference in environment.items()},
        required_environment=tuple(required),
        data_home=data_home,
    )
    target = paths.installations / "clients" / "shared" / "mcp-launchers" / f"{identifier}.json"
    try:
        atomic_write(target, json.dumps(asdict(contract), ensure_ascii=False, indent=2) + "\n")
    except OSError:
        raise AgentKitError(f"Не удалось записать контракт запуска MCP {identifier}") from None
    return target


def registration_command(paths: KitPaths, item: dict[str, Any], executable: Path) -> tuple[str, list[str]]:
    contract = write_launch_contract(paths, item, executable)
    return sys.executable, ["-m", "agent_engineering_kit.mcp_launcher", str(contract.resolve())]


def _load_contract(path: Path) -> McpLaunchContract:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise AgentKitError(f"Не удалось прочитать контракт запуска MCP: {path}") from None
    fields = {"version", "mcp_id", "command", "args", "environment", "required_environment"}
    valid = isinstance(document, dict) and (
        document.get("version") == 1 and document.keys() == fields
        or document.get("version") == 2 and document.keys() == fields | {"data_home"}
        and _canonical_data_home(document.get("data_home"))
    )
    if valid:
        valid = (
            type(document["version"]) is int and document["version"] in {1, 2}
            and _safe_identifier(document["mcp_id"])
            and isinstance(document["command"], str) and "\x00" not in document["command"]
            and Path(document["command"]).is_absolute()
            and _arguments_valid(document["args"])
            and isinstance(document["environment"], dict)
            and all(_environment_name(target) and _environment_name(source) for target, source in document["environment"].items())
            and isinstance(document["required_environment"], list)
            and all(_environment_name(name) for name in document["required_environment"])
        )
    if not valid:
        raise AgentKitError(f"Некорректный контракт запуска MCP: {path}")
    return McpLaunchContract(
        version=document["version"], mcp_id=document["mcp_id"], command=document["command"],
        args=tuple(document["args"]), environment=document["environment"],
        required_environment=tuple(document["required_environment"]),
        data_home=document.get("data_home"),
    )


def launch(
    contract_path: Path,
    *,
    paths: KitPaths | None = None,
    environ: Mapping[str, str] | None = None,
    exec_process: Callable = os.execvpe,
) -> None:
    contract = _load_contract(contract_path)
    if contract.data_home is not None:
        data = Path(contract.data_home)
        paths = KitPaths(contract_path.parent, data, data / "runtime", data / "projects", data / "overrides")
    elif paths is None:
        paths = resolve_paths()  # Совместимость с уже зарегистрированными контрактами v1.
    inherited = dict(os.environ if environ is None else environ)
    vault = McpCredentialStore(paths).load()
    sources = set(contract.environment.values()) | set(contract.required_environment)
    resolved = {source: vault.get(source) or inherited.get(source) for source in sources}
    missing = sorted(source for source in contract.required_environment if not resolved[source])
    if missing:
        raise AgentKitError(f"MCP {contract.mcp_id}: отсутствуют обязательные переменные: {', '.join(missing)}")
    child_environment = inherited.copy()
    for target, source in contract.environment.items():
        if source != target:
            child_environment.pop(source, None)
    for source in sources - set(contract.environment.values()):
        if resolved[source]:
            child_environment[source] = resolved[source]
    for target, source in contract.environment.items():
        if resolved[source]:
            child_environment[target] = resolved[source]
    try:
        exec_process(contract.command, [contract.command, *contract.args], child_environment)
    except (OSError, ValueError):
        raise AgentKitError(f"Не удалось запустить MCP {contract.mcp_id}") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent_engineering_kit.mcp_launcher")
    parser.add_argument("contract", type=Path)
    args = parser.parse_args(argv)
    try:
        launch(args.contract)
    except AgentKitError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
