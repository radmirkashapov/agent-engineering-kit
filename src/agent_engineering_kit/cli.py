"""Командный интерфейс локального декларативного управляющего слоя."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal

from .bindings import attach_project, bind_repository, load_attached_project, project_readiness, reconcile_project
from .bindings import repository_paths
from .conventions import load_conventions
from .doctor import doctor
from .errors import AgentKitError
from .explain import explain
from .external_skills import ExternalSkillManager
from .mcp_manager import McpManager
from .events import read_events
from .harness import resolve_harness
from .io import markdown_frontmatter
from .override_service import (
    GENERIC_OVERRIDE_KINDS,
    install_generic_override,
    install_mcp_override,
    install_skill_override,
    list_overrides,
    reset_component_override,
    reset_generic_override,
    resolve_scope,
    set_component_access,
)
from .overrides import apply_local_overrides
from .paths import KitPaths, resolve_paths
from .policy import effective_policy
from .profiles import compile_permission_profile, load_profiles
from .projects import LogicalProject, detect_project, find_project, init_project, validate_project_definition
from .runs import build_run_request, canonical_digest, record_run_result, run_events_path, write_run_request
from .resync import ResyncReport, resync
from .security_tools import SecurityToolManager
from .sync import record_sync, revision, update_repository
from .tasks import (
    acquire_lease,
    complete_task_workspace,
    create_task_workspace,
    garbage_collect_task_workspace,
    release_leases,
    task_workspace_path,
)
from .validation import VALIDATORS, validate
from .worktrees import create_managed_worktrees, plan_managed_worktrees
from .process import run_command


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

    overrides = subs.add_parser("override", help="Управлять всеми локальными переопределениями").add_subparsers(dest="override_command", required=True)
    override_list = overrides.add_parser("list", help="Показать определения выбранного локального слоя")
    override_list.add_argument("--scope", choices=["global", "project"], required=True)
    override_explain = overrides.add_parser("explain", help="Объяснить локальное переопределение")
    override_explain.add_argument("kind", choices=sorted(GENERIC_OVERRIDE_KINDS))
    override_explain.add_argument("id")
    override_explain.add_argument("--scope", choices=["global", "project"], required=True)
    override_set = overrides.add_parser("set", help="Записать локальное переопределение")
    override_set.add_argument("kind", choices=sorted(GENERIC_OVERRIDE_KINDS))
    override_set.add_argument("id")
    override_set.add_argument("--mode", choices=["extend", "replace", "disable"], required=True)
    override_set.add_argument("--from", dest="source", required=True, help="YAML со значением")
    override_set.add_argument("--reason", required=True, help="Проверяемая причина локального решения")
    override_set.add_argument("--scope", choices=["global", "project"], required=True)
    override_set.add_argument("--resync", action="store_true")
    override_reset = overrides.add_parser("reset", help="Сбросить локальное переопределение")
    override_reset.add_argument("kind", choices=sorted(GENERIC_OVERRIDE_KINDS))
    override_reset.add_argument("id")
    override_reset.add_argument("--scope", choices=["global", "project"], required=True)
    override_reset.add_argument("--resync", action="store_true")

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
    project_attach = project.add_parser("attach", help="Создать machine-local descriptor без изменения repository")
    project_attach.add_argument("path")
    project_attach.add_argument("--id", dest="identifier")
    project_bind = project.add_parser("bind", help="Связать объявленный repository ID с локальным путём")
    project_bind.add_argument("project")
    project_bind.add_argument("repository_id")
    project_bind.add_argument("path")
    project_reconcile = project.add_parser("reconcile", help="Показать structural diff inventory")
    project_reconcile.add_argument("project")
    project_reconcile.add_argument("--apply", action="store_true", help="Сохранить inventory в machine-local state")

    config = subs.add_parser("config").add_subparsers(dest="config_command", required=True)
    config_explain = config.add_parser("explain")
    config_explain.add_argument("path", nargs="?", default=".")
    config_explain.add_argument("--format", choices=["text", "json"], default="text")

    runs = subs.add_parser("run", help="Фиксировать контракты запуска harness").add_subparsers(dest="run_command", required=True)
    run_prepare = runs.add_parser("prepare", help="Создать request manifest")
    run_prepare.add_argument("path", nargs="?", default=".")
    run_prepare.add_argument("--run-id")
    run_prepare.add_argument("--profile", choices=["developer", "tester", "reviewer"], default="developer")
    run_prepare.add_argument("--model")
    run_prepare.add_argument("--verify", action="append", default=[])
    run_result = runs.add_parser("record-result", help="Записать фактический результат")
    run_result.add_argument("run_id")
    run_result.add_argument("--project-id")
    run_result.add_argument("--status", choices=["passed", "failed", "blocked", "cancelled"], required=True)
    run_result.add_argument("--actual-model")
    run_result.add_argument("--verification-json", default="[]")
    run_result.add_argument("--details-json", default="{}")
    run_events = runs.add_parser("events", help="Показать append-only события запуска")
    run_events.add_argument("run_id")
    run_events.add_argument("--project-id")

    tasks = subs.add_parser("task", help="Управлять изолированным workspace задачи").add_subparsers(dest="task_command", required=True)
    task_create = tasks.add_parser("create", help="Создать planning snapshot")
    task_create.add_argument("project")
    task_create.add_argument("task_id")
    task_create.add_argument("--write", action="append", required=True, dest="write_set")
    for name in ("lease", "complete", "release", "gc"):
        task_action = tasks.add_parser(name)
        task_action.add_argument("project_id")
        task_action.add_argument("task_id")
    for name in ("worktree-plan", "worktree-create"):
        task_action = tasks.add_parser(name)
        task_action.add_argument("project_id")
        task_action.add_argument("task_id")
        task_action.add_argument("--branch-prefix", required=True)
    return parser


def _render_result(result) -> int:
    for diagnostic in result.diagnostics:
        print(diagnostic.render())
    print("Результат: OK" if result.ok else "Результат: ERROR")
    return 0 if result.ok else 1


def _print_rows(rows: list[dict]) -> None:
    for row in rows:
        print(f"{row['id']}: {row.get('status', 'UNKNOWN')} ({row.get('source', row.get('category', 'managed'))})")


def _project_reference(value: str, paths: KitPaths) -> LogicalProject:
    candidate = Path(value).expanduser()
    project = find_project(candidate) if candidate.exists() else None
    if project is None:
        project = load_attached_project(value, paths)
    if project is None:
        raise AgentKitError(f"Logical project не найден: {value}")
    return project


def _print_resync_report(report: ResyncReport) -> None:
    """Вывести единообразный итог resync."""
    outcome = "Resync завершён с ограничениями" if report.incomplete else "Resync завершён"
    print(f"{outcome}: revision {report.revision}; changed={str(report.changed).lower()}")
    print(f"Skills: {len(report.skills)}; MCP: {len(report.mcp)}; clients: {len(report.clients)}")
    for limitation in report.incomplete:
        print(f"CONFIG_REQUIRED: {limitation}")


def _json_argument(value: str, *, expected: type, label: str):
    try:
        document = json.loads(value)
    except json.JSONDecodeError as error:
        raise AgentKitError(f"{label}: некорректный JSON: {error}") from error
    if not isinstance(document, expected):
        raise AgentKitError(f"{label}: ожидается {expected.__name__}")
    return document


def _repository_snapshots(
    project: LogicalProject,
    paths: KitPaths,
    *,
    require_git: bool = False,
) -> list[dict[str, str]]:
    snapshots: list[dict[str, str]] = []
    for identifier, path in sorted(repository_paths(project, paths).items()):
        completed = run_command(["git", "-C", str(path), "rev-parse", "HEAD"])
        if not completed.ok:
            if require_git:
                raise AgentKitError(f"Repository {identifier} не содержит доступный Git commit")
            snapshots.append({"id": identifier, "path": str(path)})
            continue
        snapshots.append({"id": identifier, "path": str(path), "commit": completed.stdout.strip()})
    return snapshots


def _task_path(paths: KitPaths, project_id: str, task_id: str) -> Path:
    return task_workspace_path(paths, project_id=project_id, task_id=task_id)


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
    access_profile = str(effective_policy(repository, paths, project).values["mcp.access_profile"])
    return McpManager(repository, paths).available(project, access_profile=access_profile)


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


def _handle_generic_override(
    args: argparse.Namespace,
    repository: Path,
    paths: KitPaths,
) -> int:
    """Выполнить generic override без скрытого выбора области."""
    scope = resolve_scope(paths, args.scope, Path.cwd())
    if args.override_command == "list":
        print(json.dumps(list_overrides(scope), ensure_ascii=False, indent=2))
        return 0
    if args.override_command == "explain":
        aliases = {f"{args.kind}.{args.id}"}
        if args.kind == "harness" and args.id == "client":
            aliases.add("client.preferred")
        if args.kind == "mcp" and args.id == "access-profile":
            aliases.add("mcp.access_profile")
        for row in list_overrides(scope):
            document = row["document"]
            component_match = row["kind"] == args.kind and document.get("target") == args.id
            policy_match = any(
                entry.get("key") in aliases
                for entry in document.get("overrides", [])
                if isinstance(entry, dict)
            )
            if component_match or policy_match:
                print(json.dumps(row, ensure_ascii=False, indent=2))
                return 0
        raise AgentKitError(f"Локальное переопределение не найдено: {args.kind}/{args.id}")
    if args.override_command == "set":
        changed = [
            install_generic_override(
                scope,
                args.kind,
                args.id,
                mode=args.mode,
                source=Path(args.source),
                reason=args.reason,
            )
        ]
    else:
        changed = reset_generic_override(scope, args.kind, args.id, paths.overrides / "backups")
    for path in changed:
        print(f"Изменённый путь: {path}")
    if not changed:
        print("Изменения не требовались.")
    if getattr(args, "resync", False) and changed:
        project = find_project(Path.cwd())
        _print_resync_report(resync(repository, paths, project=project, update_kit=False, force=False))
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
            access_profile = str(effective_policy(repository, paths, project).values["mcp.access_profile"])
            if args.mcp_command in {"list", "status"}:
                _print_rows(manager.list(project, access_profile=access_profile))
            elif args.mcp_command == "available":
                print(json.dumps(manager.available(project, access_profile=access_profile), ensure_ascii=False, indent=2))
            elif args.mcp_command == "explain":
                rows = manager.list(project, access_profile=access_profile)
                selected = [row for row in rows if row["id"] == args.id]
                if not selected:
                    raise AgentKitError(f"MCP не найден: {args.id}")
                print(json.dumps(selected[0], ensure_ascii=False, indent=2))
            else:
                return _mutate_resource("mcp", args, repository, paths, project)
            return 0
        if args.command == "override":
            return _handle_generic_override(args, repository, paths)
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
            project = _project_reference(args.path, paths)
            validation = validate_project_definition(project, repository)
            if not validation.ok:
                messages = "; ".join(item.message for item in validation.diagnostics if item.severity == "ERROR")
                raise AgentKitError(f"Некорректный project manifest: {messages}")
            status = project_readiness(project, paths)
            print(json.dumps({"project_id": project.identifier, **status}, ensure_ascii=False, indent=2))
            return 1 if status["status"] in {"BLOCKED", "MISMATCHED"} else 0
        if args.command == "project" and args.project_command == "attach":
            project = attach_project(Path(args.path), repository, paths, identifier=args.identifier)
            print(f"Logical project подключён: {project.identifier}\nDescriptor: {project.manifest_path}")
            return 0
        if args.command == "project" and args.project_command == "bind":
            project = _project_reference(args.project, paths)
            validation = validate_project_definition(project, repository)
            if not validation.ok:
                messages = "; ".join(item.message for item in validation.diagnostics if item.severity == "ERROR")
                raise AgentKitError(f"Некорректный project manifest: {messages}")
            binding = bind_repository(project, paths, args.repository_id, Path(args.path))
            print(f"Repository binding: {binding}")
            return 0
        if args.command == "project" and args.project_command == "reconcile":
            project = _project_reference(args.project, paths)
            preview = reconcile_project(project, paths, apply=args.apply)
            print(json.dumps(preview, ensure_ascii=False, indent=2))
            return 1 if preview["status"] in {"BLOCKED", "MISMATCHED"} else 0
        if args.command == "run" and args.run_command == "prepare":
            candidate = Path(args.path).expanduser()
            if candidate.exists():
                project = find_project(candidate)
            else:
                project = load_attached_project(args.path, paths)
                if project is None:
                    raise AgentKitError(f"Logical project или path не найден: {args.path}")
            policy = effective_policy(repository, paths, project)
            conventions = {"items": load_conventions(repository, project)}
            harness = resolve_harness(
                repository,
                project.manifest if project else None,
                policy_values=policy.values,
            )
            profile = compile_permission_profile(
                repository,
                args.profile,
                client_capabilities=set(harness["managed_capabilities"]),
            )
            profile_definition = next(
                item for item in load_profiles(repository)
                if item["id"] == args.profile
            )
            declared_roles = []
            for path in sorted((repository / "agents").glob("*.md")):
                metadata = markdown_frontmatter(path)
                declared_roles.append({
                    **metadata,
                    "id": metadata.get("id", path.stem),
                    "content": path.read_text(encoding="utf-8"),
                })
            all_roles = {
                item["id"]: item
                for item in apply_local_overrides(
                    declared_roles,
                    paths.overrides,
                    "agents",
                    project.identifier if project else None,
                )
            }
            roles = [all_roles[item] for item in profile_definition["roles"] if item in all_roles]
            skills = [
                item for item in ExternalSkillManager(
                    repository,
                    paths,
                    project_id=project.identifier if project else None,
                ).list()
                if item["id"] in profile_definition["skills"]
            ]
            mcp = [
                item for item in McpManager(repository, paths).list(
                    project,
                    access_profile=str(policy.values["mcp.access_profile"]),
                )
                if item["id"] in profile_definition["mcp"]
            ]
            manifest = build_run_request(
                kit_revision=revision(repository),
                project_id=project.identifier if project else None,
                policy=policy.as_dict(),
                conventions=conventions,
                harness=harness,
                roles=roles,
                skills=skills,
                mcp=mcp,
                requested_model=args.model,
                permissions=profile,
                repositories=_repository_snapshots(project, paths) if project else [],
                verification_steps=args.verify,
                bypasses=[{"reason": warning} for warning in policy.warnings],
                run_id=args.run_id,
            )
            print(write_run_request(paths, manifest))
            return 0
        if args.command == "run" and args.run_command == "record-result":
            target = record_run_result(
                paths,
                project_id=args.project_id,
                run_id=args.run_id,
                status=args.status,
                actual_model=args.actual_model,
                verification=_json_argument(args.verification_json, expected=list, label="verification"),
                details=_json_argument(args.details_json, expected=dict, label="details"),
            )
            print(target)
            return 0
        if args.command == "run" and args.run_command == "events":
            event_path = run_events_path(paths, project_id=args.project_id, run_id=args.run_id)
            print(json.dumps(read_events(event_path), ensure_ascii=False, indent=2))
            return 0
        if args.command == "task" and args.task_command == "create":
            project = _project_reference(args.project, paths)
            policy = effective_policy(repository, paths, project)
            conventions = {"items": load_conventions(repository, project)}
            target = create_task_workspace(
                paths,
                project_id=project.identifier,
                task_id=args.task_id,
                repositories=_repository_snapshots(project, paths, require_git=True),
                write_set=args.write_set,
                policy_digest=canonical_digest(policy.as_dict()),
                conventions_digest=canonical_digest(conventions),
            )
            print(target)
            return 0
        if args.command == "task":
            task_path = _task_path(paths, args.project_id, args.task_id)
            if not task_path.is_file():
                raise AgentKitError(f"Task workspace не найден: {task_path}")
            task_document = json.loads(task_path.read_text(encoding="utf-8"))
            if args.task_command == "lease":
                print(acquire_lease(
                    paths,
                    project_id=args.project_id,
                    task_id=args.task_id,
                    write_set=list(task_document["write_set"]),
                ))
                return 0
            if args.task_command == "complete":
                print(complete_task_workspace(
                    paths,
                    project_id=args.project_id,
                    task_id=args.task_id,
                ))
                return 0
            if args.task_command == "release":
                released = release_leases(paths, project_id=args.project_id, task_id=args.task_id)
                print(json.dumps([str(path) for path in released], ensure_ascii=False))
                return 0
            if args.task_command == "gc":
                removed = garbage_collect_task_workspace(
                    paths,
                    project_id=args.project_id,
                    task_id=args.task_id,
                )
                print(json.dumps([str(path) for path in removed], ensure_ascii=False))
                return 0
            plans = plan_managed_worktrees(paths, task_path, branch_prefix=args.branch_prefix)
            if args.task_command == "worktree-create":
                plans = create_managed_worktrees(paths, task_path, plans)
            print(json.dumps(plans, ensure_ascii=False, indent=2))
            return 0
        if args.command == "config" and args.config_command == "explain":
            print(explain(repository, paths, Path(args.path), output_format=args.format), end="")
            return 0
    except AgentKitError as error:
        print(f"ERROR   [agent-kit] {error}", file=sys.stderr)
        return 1
    return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
