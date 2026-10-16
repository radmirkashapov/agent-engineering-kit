"""Высокоуровневые автоматические команды разработчика."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .cli import run as run_agent_kit
from .errors import AgentKitError
from .issue_context import resolve_issue
from .mcp_client import McpToolClient
from .paths import resolve_paths
from .projects import find_project


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent", description="Автоматический workflow Agent Engineering Kit")
    commands = parser.add_subparsers(dest="command", required=True)
    tasks = commands.add_parser("task").add_subparsers(dest="task_command", required=True)
    create = tasks.add_parser("create", help="Создать задачу, ветку и worktree")
    create.add_argument("reference", help="Jira URL либо task ID")
    create.add_argument("--type", dest="branch_type")
    create.add_argument("--write", action="append", dest="write_set")
    lanes = tasks.add_parser("lane").add_subparsers(dest="lane_command", required=True)
    lane_create = lanes.add_parser("create")
    lane_create.add_argument("task_id")
    lane_create.add_argument("lane_id")
    lane_create.add_argument("--write", action="append", required=True, dest="write_set")
    for name in ("status", "integrate", "complete"):
        lane = lanes.add_parser(name)
        lane.add_argument("task_id")
        lane.add_argument("lane_id", nargs="?" if name == "status" else None)
    return parser


def _default_write_set(project_root: Path, current: Path) -> list[str]:
    """Выбрать безопасную область текущего компонента либо всего проекта."""
    try:
        relative = current.resolve().relative_to(project_root.resolve())
    except ValueError:
        return ["**/*"]
    return ["**/*"] if relative == Path(".") else [f"{relative.as_posix()}/**"]


def run(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = resolve_paths()
    project = find_project(Path.cwd())
    if project is None:
        print("ERROR: Logical project не найден; выполните agent-kit project init", file=sys.stderr)
        return 1
    try:
        if args.task_command == "create":
            jira = project.manifest.get("integrations", {}).get("jira")
            issue = resolve_issue(
                args.reference,
                jira=jira if isinstance(jira, dict) else None,
                client=McpToolClient(paths.repository, paths, project=project),
            )
            branch_type = args.branch_type or issue.branch_type or "feat"
            write_set = args.write_set or _default_write_set(project.root, Path.cwd())
            translated = ["task", "create", issue.task_id, "--type", branch_type]
            if issue.summary:
                translated.extend(["--summary", issue.summary])
            for pattern in write_set:
                translated.extend(["--write", pattern])
            return run_agent_kit(translated)
        translated = ["task", "lane", args.lane_command, args.task_id]
        if args.lane_id:
            translated.append(args.lane_id)
        for pattern in getattr(args, "write_set", []) or []:
            translated.extend(["--write", pattern])
        return run_agent_kit(translated)
    except AgentKitError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(run())
