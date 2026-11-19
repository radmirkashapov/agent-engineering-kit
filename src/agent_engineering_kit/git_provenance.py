"""Единый, client-neutral маршрут для provenance AI-коммитов."""

from __future__ import annotations

from pathlib import Path

from .errors import AgentKitError
from .process import run_command


CLIENT_IDS = ("codex", "claude-code", "claude-desktop", "opencode", "cline")
HOOK_MARKER = "# agent-engineering-kit:provenance-hook"


def _git(root: Path, *args: str) -> str:
    result = run_command(["git", "-C", str(root), *args])
    if not result.ok:
        raise AgentKitError(result.stderr.strip() or "Не удалось выполнить Git-команду")
    return result.stdout.strip()


def _append_trailers(message: str, client: str) -> str:
    """Добавить ровно два managed trailers, сохранив пользовательский текст."""
    if client not in CLIENT_IDS:
        raise AgentKitError(f"Неизвестный AI client: {client}")
    lines = message.rstrip().splitlines()
    trailers = {
        "Agent-Generated": "true",
        "Agent-Client": client,
    }
    found: dict[str, int] = {}
    for index, line in enumerate(lines):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key in trailers and value.strip():
            found[key] = index
    for key, value in trailers.items():
        rendered = f"{key}: {value}"
        if key in found:
            lines[found[key]] = rendered
    missing = [f"{key}: {value}" for key, value in trailers.items() if key not in found]
    if missing:
        if lines:
            lines.append("")
        lines.extend(missing)
    return "\n".join(lines) + "\n"


def commit(root: Path, *, client: str, message: str, amend: bool = False) -> None:
    """Создать агентный коммит с проверяемыми trailers без смены Git author."""
    if not message.strip():
        raise AgentKitError("Сообщение коммита не может быть пустым")
    if client not in CLIENT_IDS:
        raise AgentKitError(f"Неизвестный AI client: {client}")
    rendered = _append_trailers(message, client)
    command = ["git", "-C", str(root), "-c", f"agent-kit.provenance.active-client={client}", "commit", "-m", rendered]
    if amend:
        command.append("--amend")
    result = run_command(command)
    if not result.ok:
        raise AgentKitError(result.stderr.strip() or result.stdout.strip() or "Git commit завершился ошибкой")


def _hooks_directory(root: Path) -> Path:
    path = Path(_git(root, "rev-parse", "--git-path", "hooks"))
    return path if path.is_absolute() else root / path


def install_hook(root: Path) -> Path | None:
    """Установить консервативный hook, не перезаписывая чужой hook."""
    result = run_command(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"])
    if not result.ok or result.stdout.strip() != "true":
        return None
    target = _hooks_directory(root) / "prepare-commit-msg"
    if target.exists() and HOOK_MARKER not in target.read_text(encoding="utf-8", errors="replace"):
        raise AgentKitError(
            f"Нельзя установить provenance hook: уже существует пользовательский hook {target}. "
            "Добавьте в него вызов `agent-kit git prepare-commit-msg \"$1\"` вручную."
        )
    content = (
        "#!/bin/sh\n"
        f"{HOOK_MARKER}\n"
        "# Git for Windows также запускает hooks через sh.\n"
        "agent-kit git prepare-commit-msg \"$1\"\n"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    target.chmod(target.stat().st_mode | 0o111)
    return target


def prepare_commit_msg(root: Path, message_path: Path) -> bool:
    """Hook endpoint: нормализовать trailers для wrapper/session Git config."""
    configured = run_command(["git", "-C", str(root), "config", "--get", "agent-kit.provenance.active-client"])
    client = configured.stdout.strip() if configured.ok else ""
    strict = run_command(["git", "-C", str(root), "config", "--bool", "--get", "agent-kit.provenance.strict"])
    if strict.ok and strict.stdout.strip() == "true" and not client:
        raise AgentKitError(
            "Для strict agent worktree прямой git commit запрещён; используйте "
            "agent-kit git commit --client <client-id> -m <message>"
        )
    if not client:
        return False
    if client not in CLIENT_IDS:
        raise AgentKitError(f"Некорректный agent-kit.provenance.client: {client}")
    try:
        original = message_path.read_text(encoding="utf-8")
    except OSError as error:
        raise AgentKitError(f"Не удалось прочитать сообщение коммита: {message_path}") from error
    updated = _append_trailers(original, client)
    if updated != original:
        message_path.write_text(updated, encoding="utf-8")
    return True


def mark_agent_worktree(root: Path, *, client: str) -> None:
    """Включить строгую provenance-политику для созданного агентного worktree."""
    if client not in CLIENT_IDS:
        raise AgentKitError(f"Неизвестный AI client: {client}")
    _git(root, "config", "--worktree", "agent-kit.provenance.client", client)
    _git(root, "config", "--worktree", "agent-kit.provenance.strict", "true")
    install_hook(root)


def unmark_agent_worktree(root: Path) -> None:
    """Снять strict guard после завершения работы агента."""
    for key in ("agent-kit.provenance.client", "agent-kit.provenance.strict"):
        run_command(["git", "-C", str(root), "config", "--worktree", "--unset-all", key])

