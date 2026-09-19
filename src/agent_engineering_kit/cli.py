"""CLI agent-kit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .doctor import doctor
from .errors import AgentKitError
from .explain import explain
from .paths import resolve_paths
from .projects import find_project, init_project, register_memory, validate_project
from .sync import record_sync, update_repository
from .validation import VALIDATORS, validate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-kit", description="Универсальный engineering kit для AI coding agents")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Проверить repository и effective policy")
    validate_parser.add_argument("target", nargs="?", default="all", choices=["all", *VALIDATORS])
    validate_parser.add_argument("--ci", action="store_true", help="Исключить все user-local inputs")

    subparsers.add_parser("doctor", help="Проверить installation и runtime")
    sync_parser = subparsers.add_parser("sync", help="Обновить kit и сгенерировать thin adapters")
    sync_parser.add_argument("--no-update", action="store_true", help="Не выполнять git fetch/pull")

    project_parser = subparsers.add_parser("project", help="Управлять logical project")
    project_commands = project_parser.add_subparsers(dest="project_command", required=True)
    init_parser = project_commands.add_parser("init", help="Создать .ai-team/project.yaml")
    init_parser.add_argument("path", nargs="?", default=".")
    init_parser.add_argument("--id", dest="identifier")
    status_parser = project_commands.add_parser("status", help="Показать и проверить logical project")
    status_parser.add_argument("path", nargs="?", default=".")

    config_parser = subparsers.add_parser("config", help="Effective configuration")
    config_commands = config_parser.add_subparsers(dest="config_command", required=True)
    explain_parser = config_commands.add_parser("explain", help="Объяснить precedence и provenance")
    explain_parser.add_argument("path", nargs="?", default=".")
    return parser


def _render_result(result) -> int:
    for diagnostic in result.diagnostics:
        print(diagnostic.render())
    print("Результат: OK" if result.ok else "Результат: ERROR")
    return 0 if result.ok else 1


def run(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    paths = resolve_paths()
    repository = paths.repository
    try:
        if arguments.command == "validate":
            return _render_result(validate(repository, paths, arguments.target, include_local=not arguments.ci))
        if arguments.command == "doctor":
            return _render_result(doctor(repository, paths))
        if arguments.command == "sync":
            if not arguments.no_update:
                update_repository(repository)
            preliminary = validate(repository, paths, "all", include_local=True)
            if not preliminary.ok:
                return _render_result(preliminary)
            current_revision, generated = record_sync(repository, paths)
            print(f"Sync завершён. Session revision: {current_revision}")
            print(f"Сгенерировано client adapters: {len(generated)}")
            return 0
        if arguments.command == "project" and arguments.project_command == "init":
            project = init_project(Path(arguments.path), repository, paths, identifier=arguments.identifier)
            print(f"Logical project создан/найден: {project.identifier}")
            print(f"Manifest: {project.manifest_path}")
            print(f"Memory: {paths.projects / project.identifier}")
            return 0
        if arguments.command == "project" and arguments.project_command == "status":
            project = find_project(Path(arguments.path))
            if not project:
                raise AgentKitError("Logical project не найден: ожидается .ai-team/project.yaml")
            result = validate_project(project, repository)
            if result.ok:
                memory = register_memory(project, paths)
                result.info("projects", f"Project root: {project.root}")
                result.info("projects", f"Local memory: {memory}")
            return _render_result(result)
        if arguments.command == "config" and arguments.config_command == "explain":
            print(explain(repository, paths, Path(arguments.path)), end="")
            return 0
    except AgentKitError as error:
        print(f"ERROR   [agent-kit] {error}", file=sys.stderr)
        return 1
    return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
