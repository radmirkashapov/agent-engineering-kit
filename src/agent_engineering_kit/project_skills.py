"""Изолированный Git checkout project skills и machine-local выбор ветки."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urlsplit, urlunsplit

from .errors import AgentKitError
from .external_skills import SkillValidator
from .io import atomic_write, load_json
from .paths import KitPaths
from .process import CommandResult, run_command
from .projects import LogicalProject
from .security_tools import SecurityToolManager


@dataclass(frozen=True)
class ProjectSkillsSource:
    url: str
    default_branch: str


def redact_url(value: str) -> str:
    """Убрать userinfo, query и fragment из URL, в том числе в Git diagnostic."""
    def redact(match: re.Match[str]) -> str:
        try:
            parsed = urlsplit(match.group())
            return urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", ""))
        except ValueError:
            return match.group().split("://", 1)[0] + "://<redacted>"

    return re.sub(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s'\"<>]+", redact, value)


@contextmanager
def _repository_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if os.name == "nt":  # pragma: no cover — проверяется на Windows.
            import msvcrt

            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":  # pragma: no cover
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


class ProjectSkillRepositoryManager:
    def __init__(
        self,
        repository: Path,
        paths: KitPaths,
        project: LogicalProject,
        *,
        validator: SkillValidator | None = None,
        runner: Callable[..., CommandResult] = run_command,
    ) -> None:
        self.repository = repository
        self.paths = paths
        self.project = project
        self.runner = runner
        self.validator = validator or SecurityToolManager(repository, paths, runner=runner).validate_skill

    @property
    def root(self) -> Path:
        return self.paths.projects / self.project.identifier / "skills-repository"

    @property
    def override_path(self) -> Path:
        return self.root / "branch-override.json"

    @property
    def checkout(self) -> Path:
        return self.root / "checkout"

    @property
    def lock_path(self) -> Path:
        return self.paths.locks / f"project-skills-{self.project.identifier}.lock"

    def source(self) -> ProjectSkillsSource:
        value = self.project.skills_repository
        if value is None:
            raise AgentKitError("Источник project-skills не настроен")
        return ProjectSkillsSource(value["url"].strip().rstrip("/"), value["default_branch"])

    def _check_branch(self, branch: str) -> None:
        if not isinstance(branch, str) or not branch or branch.startswith("-") or "@{" in branch:
            raise AgentKitError("Некорректное имя ветки project-skills")
        checked = self.runner(["git", "check-ref-format", "--branch", branch])
        if not checked.ok or checked.stdout.strip() != branch:
            raise AgentKitError("Некорректное имя ветки project-skills")

    def requested_branch(self, *, ci: bool = False) -> str:
        source = self.source()
        if ci or not self.override_path.is_file():
            return source.default_branch
        branch = load_json(self.override_path).get("branch")
        self._check_branch(branch)
        return branch

    def _selection_dict(self) -> dict[str, object]:
        source = self.source()
        return {
            "project_id": self.project.identifier,
            "source_url": redact_url(source.url),
            "default_branch": source.default_branch,
            "requested_branch": self.requested_branch(),
            "local_override_applied": self.override_path.is_file(),
        }

    def _check_storage(self) -> None:
        # Git -C не должен следовать ссылке в product checkout; проверяем также
        # родителей, через которых создаются override и candidate.
        managed = [self.paths.projects, self.root.parent, self.root, self.checkout,
                   self.checkout / ".git", self.root / "candidates"]
        for path in managed:
            if path.is_symlink() or (path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
                raise AgentKitError("Небезопасная ссылка в managed-хранилище project-skills")

    def set_branch(self, branch: str) -> dict[str, object]:
        self.source()
        self._check_storage()
        self._check_branch(branch)
        with _repository_lock(self.lock_path):
            atomic_write(self.override_path, json.dumps({"branch": branch}) + "\n")
            os.chmod(self.override_path, 0o600)
            return self._selection_dict()

    def use_main(self) -> dict[str, object]:
        self.source()
        self._check_storage()
        with _repository_lock(self.lock_path):
            self.override_path.unlink(missing_ok=True)
            return self._selection_dict()

    def _git(self, args: list[str]) -> str:
        try:
            result = self.runner(["git", *args])
        except OSError as error:
            raise AgentKitError(f"Ошибка Git project-skills: {redact_url(str(error))}") from None
        if not result.ok:
            detail = redact_url((result.stderr or result.stdout).strip())
            raise AgentKitError(f"Ошибка Git project-skills: {detail}")
        return result.stdout.strip()

    def _discard_candidate(self, candidate: Path) -> None:
        removed = self.runner(["git", "-C", str(self.checkout), "worktree", "remove", "--force", str(candidate)])
        if not removed.ok:
            if candidate.is_symlink():
                candidate.unlink()
            elif candidate.exists():
                shutil.rmtree(candidate)
            self._git(["-C", str(self.checkout), "worktree", "prune"])

    def fetch_candidate(self, *, ci: bool = False) -> tuple[Path, str]:
        source = self.source()
        self._check_storage()
        with _repository_lock(self.lock_path):
            branch = self.requested_branch(ci=ci)
            self._check_branch(branch)
            self.root.mkdir(parents=True, exist_ok=True)
            if not self.checkout.exists():
                try:
                    self._git(["clone", "--quiet", "--no-checkout", "--", source.url, str(self.checkout)])
                except Exception:
                    if self.checkout.exists():
                        shutil.rmtree(self.checkout)
                    raise
            if not (self.checkout / ".git").is_dir():
                raise AgentKitError("Некорректный managed checkout project-skills")
            self._git(["-C", str(self.checkout), "remote", "set-url", "origin", source.url])
            # Явный refspec обновляет remote ref также после force push/rewind.
            remote_ref = f"refs/remotes/origin/{branch}"
            self._git(["-C", str(self.checkout), "fetch", "--quiet", "--prune", "origin",
                       f"+refs/heads/{branch}:{remote_ref}"])
            revision = self._git(["-C", str(self.checkout), "rev-parse", "--verify", f"{remote_ref}^{{commit}}"])
            candidate = self.root / "candidates" / str(uuid.uuid4())
            candidate.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._git(["-C", str(self.checkout), "worktree", "add", "--detach", str(candidate), revision])
            except Exception:
                self._discard_candidate(candidate)
                raise
            return candidate, revision
