"""CLI agent-kit: declarative control plane для одной машины."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal

from .doctor import doctor
from .errors import AgentKitError
from .explain import explain
from .external_skills import ExternalSkillManager
from .mcp_manager import McpManager
from .override_service import (
    install_mcp_override,
    install_skill_override,
    reset_component_override,
    resolve_scope,
    set_component_access,
)
from .paths import KitPaths, resolve_paths
from .projects import LogicalProject, detect_project, find_project, init_project, register_memory, validate_project
from .resync import ResyncReport, resync
from .security_tools import SecurityToolManager
from .sync import record_sync, update_repository
from .validation import VALIDATORS, validate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-kit", description="Универсальный engineering kit для AI coding agents")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("install", help="Установить desired-state environment без обновления checkout")
    check = subs.add_parser("validate", help="Проверить repository и effective policy")
    check.add_argument("target", nargs="?", default="all", choices=["all", *VALIDATORS])
    check.add_argument("--ci", action="store_true", help="Исключить user-local inputs")
    subs.add_parser("doctor", help="Проверить installation и runtime")
    for name in ("sync", "resync"):
        command = subs.add_parser(name, help="Привести машину к desired state")
        command.add_argument("--no-update", action="store_true")
        command.add_argument("--force", action="store_true")

    skills = subs.add_parser("skills", help="Управлять skills").add_subparsers(dest="skills_command", required=True)
    skills.add_parser("list", help="Показать состояние skills")
    skills.add_parser("status", help="Показать состояние skills")
    skills.add_parser("available", help="Показать полный доступный каталог skills")
    for name, help_text in (
        ("enable", "Разрешить skill"),
        ("disable", "Отключить skill"),
        ("reset", "Сбросить локальные настройки skill"),
    ):
        command = skills.add_parser(name, help=help_text)
        command.add_argument("id", help="ID skill")
        command.add_argument("--scope", choices=["global", "project"], required=True, help="Область изменения")
        command.add_argument("--resync", action="store_true", help="Выполнить resync после успешного изменения")
    skill_override = skills.add_parser("override", help="Установить локальную реализацию skill")
    skill_override.add_argument("id", help="ID skill")
    skill_override.add_argument("--from", dest="source", required=True, help="Каталог с SKILL.md")
    skill_override.add_argument("--scope", choices=["global", "project"], required=True, help="Область изменения")
    skill_override.add_argument("--resync", action="store_true", help="Выполнить resync после успешного изменения")
    skill_explain = skills.add_parser("explain", help="Объяснить итоговое состояние skill")
    skill_explain.add_argument("id")
    skill_rollback = skills.add_parser("rollback", help="Вернуть предыдущую установленную ревизию skill")
    skill_rollback.add_argument("id")

    mcp = subs.add_parser("mcp", help="Управлять MCP").add_subparsers(dest="mcp_command", required=True)
    mcp.add_parser("list", help="Показать состояние MCP")
    mcp.add_parser("status", help="Показать состояние MCP")
    mcp.add_parser("available", help="Показать полный доступный каталог MCP")
    for name, help_text in (
        ("enable", "Разрешить MCP"),
        ("disable", "Отключить MCP"),
        ("reset", "Сбросить локальные настройки MCP"),
    ):
        command = mcp.add_parser(name, help=help_text)
        command.add_argument("id", help="ID MCP")
        command.add_argument("--scope", choices=["global", "project"], required=True, help="Область изменения")
        command.add_argument("--resync", action="store_true", help="Выполнить resync после успешного изменения")
    mcp_override = mcp.add_parser("override", help="Установить локальную конфигурацию MCP")
    mcp_override.add_argument("id", help="ID MCP")
    mcp_override.add_argument("--from", dest="source", required=True, help="YAML-файл переопределения")
    mcp_override.add_argument("--scope", choices=["global", "project"], required=True, help="Область изменения")
    mcp_override.add_argument("--resync", action="store_true", help="Выполнить resync после успешного изменения")
    mcp_explain = mcp.add_parser("explain", help="Объяснить итоговое состояние MCP")
    mcp_explain.add_argument("id")

    security = subs.add_parser("security").add_subparsers(dest="security_command", required=True)
    for name in ("status", "doctor", "install", "update"):
        security.add_parser(name)
    security_validate = security.add_parser("validate")
    security_validate.add_argument("path", nargs="?", default="skills/first-party")

    project = subs.add_parser("project").add_subparsers(dest="project_command", required=True)
    project_init = project.add_parser("init")
    project_init.add_argument("path", nargs="?", default=".")
    project_init.add_argument("--id", dest="identifier")
    for name in ("detect", "status"):
        command = project.add_parser(name)
        command.add_argument("path", nargs="?", default=".")

    config = subs.add_parser("config").add_subparsers(dest="config_command", required=True)
    config_explain = config.add_parser("explain")
    config_explain.add_argument("path", nargs="?", default=".")
    return parser


def _render_result(result) -> int:
    for diagnostic in result.diagnostics:
        print(diagnostic.render())
    print("Результат: OK" if result.ok else "Результат: ERROR")
    return 0 if result.ok else 1


def _print_rows(rows: list[dict]) -> None:
    for row in rows:
        print(f"{row['id']}: {row.get('status', 'UNKNOWN')} ({row.get('source', row.get('category', 'managed'))})")


def _print_resync_report(report: ResyncReport) -> None:
    """Вывести единообразный итог resync."""
    outcome = "Resync завершён с ограничениями" if report.incomplete else "Resync завершён"
    print(f"{outcome}: revision {report.revision}; changed={str(report.changed).lower()}")
    print(f"Skills: {len(report.skills)}; MCP: {len(report.mcp)}; clients: {len(report.clients)}")
    for limitation in report.incomplete:
        print(f"CONFIG_REQUIRED: {limitation}")


def _available_resources(
    kind: Literal["skills", "mcp"],
    repository: Path,
    paths: KitPaths,
    project: LogicalProject | None,
) -> list[dict]:
    """Получить полный каталог ресурса с итоговыми решениями доступа."""
    if kind == "skills":
        return ExternalSkillManager(
            repository,
            paths,
            project_id=project.identifier if project else None,
        ).available()
    return McpManager(repository, paths).available(project)


def _mutate_resource(
    kind: Literal["skills", "mcp"],
    args: argparse.Namespace,
    repository: Path,
    paths: KitPaths,
    project: LogicalProject | None,
) -> int:
    """Выполнить проверенную мутацию через сервис локальных переопределений."""
    label = "Skill" if kind == "skills" else "MCP"
    available = _available_resources(kind, repository, paths, project)
    if not any(row["id"] == args.id for row in available):
        raise AgentKitError(f"{label} не найден: {args.id}")

    scope = resolve_scope(paths, args.scope, Path.cwd())
    command = getattr(args, f"{kind}_command")
    if command == "enable":
        changed = [set_component_access(scope, kind, args.id, enabled=True)]
    elif command == "disable":
        changed = [set_component_access(scope, kind, args.id, enabled=False)]
    elif command == "override":
        source = Path(args.source)
        changed = [
            install_skill_override(scope, args.id, source)
            if kind == "skills"
            else install_mcp_override(scope, args.id, source)
        ]
    else:
        changed = reset_component_override(scope, kind, args.id, paths.overrides / "backups")

    if changed:
        for path in changed:
            print(f"Изменённый путь: {path}")
    else:
        print("Изменения не требовались.")
    effective = next(row for row in _available_resources(kind, repository, paths, project) if row["id"] == args.id)
    print("Итоговое решение:")
    print(json.dumps(effective, ensure_ascii=False, indent=2))

    if args.resync and changed:
        report = resync(repository, paths, project=project, update_kit=False, force=False)
        _print_resync_report(report)
    return 0


def run(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = resolve_paths()
    repository = paths.repository
    try:
        if args.command == "validate":
            return _render_result(validate(repository, paths, args.target, include_local=not args.ci))
        if args.command == "doctor":
            return _render_result(doctor(repository, paths))
        if args.command in {"install", "resync"}:
            project = find_project(Path.cwd())
            report = resync(repository, paths, project=project, update_kit=args.command == "resync" and not getattr(args, "no_update", False), force=getattr(args, "force", False))
            _print_resync_report(report)
            return 0
        if args.command == "sync":
            if not args.no_update:
                update_repository(repository)
            preliminary = validate(repository, paths, "all", include_local=True)
            if not preliminary.ok:
                return _render_result(preliminary)
            current_revision, generated = record_sync(repository, paths)
            print(f"Compatibility sync завершён. Session revision: {current_revision}; adapters: {len(generated)}")
            return 0
        if args.command == "skills":
            project = find_project(Path.cwd())
            manager = ExternalSkillManager(repository, paths, project_id=project.identifier if project else None)
            if args.skills_command in {"list", "status"}:
                _print_rows(manager.list())
            elif args.skills_command == "available":
                print(json.dumps(manager.available(), ensure_ascii=False, indent=2))
            elif args.skills_command == "explain":
                rows = manager.list()
                selected = [row for row in rows if row["id"] == args.id]
                if not selected:
                    raise AgentKitError(f"Skill не найден: {args.id}")
                print(json.dumps(selected[0], ensure_ascii=False, indent=2))
            elif args.skills_command == "rollback":
                print(json.dumps(manager.rollback(args.id), ensure_ascii=False, indent=2))
            else:
                return _mutate_resource("skills", args, repository, paths, project)
            return 0
        if args.command == "mcp":
            project = find_project(Path.cwd())
            manager = McpManager(repository, paths)
            if args.mcp_command in {"list", "status"}:
                _print_rows(manager.list(project))
            elif args.mcp_command == "available":
                print(json.dumps(manager.available(project), ensure_ascii=False, indent=2))
            elif args.mcp_command == "explain":
                rows = manager.list(project)
                selected = [row for row in rows if row["id"] == args.id]
                if not selected:
                    raise AgentKitError(f"MCP не найден: {args.id}")
                print(json.dumps(selected[0], ensure_ascii=False, indent=2))
            else:
                return _mutate_resource("mcp", args, repository, paths, project)
            return 0
        if args.command == "security":
            manager = SecurityToolManager(repository, paths)
            if args.security_command == "status":
                _print_rows(manager.status())
                return 0
            if args.security_command == "doctor":
                return _render_result(manager.doctor())
            if args.security_command in {"install", "update"}:
                return _render_result(manager.install(force=args.security_command == "update"))
            ok, evidence = manager.validate_skill(Path(args.path).resolve())
            print(json.dumps(evidence, ensure_ascii=False, indent=2))
            return 0 if ok else 1
        if args.command == "project" and args.project_command == "init":
            project = init_project(Path(args.path), repository, paths, identifier=args.identifier)
            print(f"Logical project создан/найден: {project.identifier}\nManifest: {project.manifest_path}\nMemory: {paths.projects / project.identifier}")
            return 0
        if args.command == "project" and args.project_command == "detect":
            print(json.dumps(detect_project(Path(args.path)), ensure_ascii=False, indent=2))
            return 0
        if args.command == "project" and args.project_command == "status":
            project = find_project(Path(args.path))
            if not project:
                raise AgentKitError("Logical project не найден: ожидается .ai-team/project.yaml")
            result = validate_project(project, repository)
            if result.ok:
                result.info("projects", f"Project root: {project.root}")
                result.info("projects", f"Local memory: {register_memory(project, paths)}")
            return _render_result(result)
        if args.command == "config" and args.config_command == "explain":
            print(explain(repository, paths, Path(args.path)), end="")
            return 0
    except AgentKitError as error:
        print(f"ERROR   [agent-kit] {error}", file=sys.stderr)
        return 1
    return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
