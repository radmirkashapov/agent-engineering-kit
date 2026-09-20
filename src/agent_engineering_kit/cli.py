"""CLI agent-kit: declarative control plane для одной машины."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .doctor import doctor
from .errors import AgentKitError
from .explain import explain
from .external_skills import ExternalSkillManager
from .mcp_manager import McpManager
from .paths import resolve_paths
from .projects import detect_project, find_project, init_project, register_memory, validate_project
from .resync import resync
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

    skills = subs.add_parser("skills").add_subparsers(dest="skills_command", required=True)
    skills.add_parser("list")
    skills.add_parser("status")
    skill_explain = skills.add_parser("explain")
    skill_explain.add_argument("id")
    skill_rollback = skills.add_parser("rollback")
    skill_rollback.add_argument("id")

    mcp = subs.add_parser("mcp").add_subparsers(dest="mcp_command", required=True)
    mcp.add_parser("list")
    mcp.add_parser("status")
    mcp_explain = mcp.add_parser("explain")
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
            outcome = "Resync завершён с ограничениями" if report.incomplete else "Resync завершён"
            print(f"{outcome}: revision {report.revision}; changed={str(report.changed).lower()}")
            print(f"Skills: {len(report.skills)}; MCP: {len(report.mcp)}; clients: {len(report.clients)}")
            for limitation in report.incomplete:
                print(f"CONFIG_REQUIRED: {limitation}")
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
            rows = manager.list()
            if args.skills_command in {"list", "status"}:
                _print_rows(rows)
            elif args.skills_command == "explain":
                selected = [row for row in rows if row["id"] == args.id]
                if not selected:
                    raise AgentKitError(f"Skill не найден: {args.id}")
                print(json.dumps(selected[0], ensure_ascii=False, indent=2))
            else:
                print(json.dumps(manager.rollback(args.id), ensure_ascii=False, indent=2))
            return 0
        if args.command == "mcp":
            rows = McpManager(repository, paths).list(find_project(Path.cwd()))
            if args.mcp_command in {"list", "status"}:
                _print_rows(rows)
            else:
                selected = [row for row in rows if row["id"] == args.id]
                if not selected:
                    raise AgentKitError(f"MCP не найден: {args.id}")
                print(json.dumps(selected[0], ensure_ascii=False, indent=2))
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
