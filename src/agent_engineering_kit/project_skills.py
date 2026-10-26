"""Изолированный Git checkout project skills и machine-local выбор ветки."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Literal
from urllib.parse import urlsplit, urlunsplit

from .errors import AgentKitError
from .external_skills import SkillValidator
from .io import atomic_write, load_json, markdown_frontmatter
from .paths import KitPaths
from .process import CommandResult, run_command
from .projects import LogicalProject
from .security_tools import SecurityToolManager


# Список repository-local selectors из `git rev-parse --local-env-vars`;
# namespace и вся GIT_CONFIG_* family также могут перенаправить Git state.
_GIT_STATE_ENVIRONMENT = frozenset({
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_OBJECT_DIRECTORY",
    "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX", "GIT_INTERNAL_SUPER_PREFIX", "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR", "GIT_NAMESPACE",
})


@dataclass(frozen=True)
class ProjectSkillsSource:
    url: str
    default_branch: str


@dataclass(frozen=True)
class ProjectSkillsStatus:
    project_id: str
    source_url: str | None
    default_branch: str | None
    requested_branch: str | None
    resolved_revision: str | None
    active_revision: str | None
    state: Literal["ACTIVE", "STALE", "UPDATE_REJECTED", "NOT_CONFIGURED"]
    reason: str | None
    updated_at: str | None
    skills: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "source_url": redact_url(self.source_url),
            "default_branch": self.default_branch,
            "requested_branch": self.requested_branch,
            "resolved_revision": self.resolved_revision,
            "active_revision": self.active_revision,
            "state": self.state,
            "reason": redact_url(self.reason),
            "updated_at": self.updated_at,
            "skills": list(self.skills),
        }


def redact_url(value: str | None) -> str | None:
    """Убрать userinfo, query и fragment из URL, в том числе в Git diagnostic."""
    def redact(match: re.Match[str]) -> str:
        try:
            parsed = urlsplit(match.group())
            return urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", ""))
        except ValueError:
            return match.group().split("://", 1)[0] + "://<redacted>"

    if value is None:
        return None
    return re.sub(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s'\"<>]+", redact, value)


def _redacted(value: Any) -> Any:
    if isinstance(value, str):
        return redact_url(value)
    if isinstance(value, dict):
        return {key: _redacted(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redacted(item) for item in value]
    return value


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
        checked = self._run_git(["check-ref-format", "--branch", branch])
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
                   self.checkout / ".git", self.root / "candidates", self.root / "revisions",
                   self.root / "active.json", self.root / "status.json"]
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

    def _run_git(self, args: list[str]) -> CommandResult:
        # `git -C` не перекрывает inherited GIT_DIR/INDEX_FILE и другие
        # selectors. Отказываем до subprocess, не меняя process-wide environ.
        if any(name in _GIT_STATE_ENVIRONMENT or name.startswith("GIT_CONFIG_") for name in os.environ):
            raise AgentKitError("Небезопасное окружение Git project-skills: очистите repository-local переменные")
        return self.runner(["git", *args])

    def _git(self, args: list[str]) -> str:
        try:
            result = self._run_git(args)
        except OSError as error:
            raise AgentKitError(f"Ошибка Git project-skills: {redact_url(str(error))}") from None
        if not result.ok:
            detail = redact_url((result.stderr or result.stdout).strip())
            raise AgentKitError(f"Ошибка Git project-skills: {detail}")
        return result.stdout.strip()

    def _discard_candidate(self, candidate: Path) -> None:
        removed = self._run_git(["-C", str(self.checkout), "worktree", "remove", "--force", str(candidate)])
        if not removed.ok:
            if candidate.is_symlink():
                candidate.unlink()
            elif candidate.exists():
                shutil.rmtree(candidate)
            self._git(["-C", str(self.checkout), "worktree", "prune"])

    def fetch_candidate(self, *, ci: bool = False) -> tuple[Path, str]:
        self.source()
        self._check_storage()
        with _repository_lock(self.lock_path):
            return self._fetch_candidate(ci=ci)

    def _fetch_candidate(self, *, ci: bool = False) -> tuple[Path, str]:
        """Вызывается только под общей блокировкой fetch → validation → activation."""
        source = self.source()
        self._check_storage()
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

    def _not_configured(self) -> ProjectSkillsStatus:
        return ProjectSkillsStatus(self.project.identifier, None, None, None, None, None,
                                   "NOT_CONFIGURED", None, None, ())

    def _structure(self, candidate: Path) -> dict[str, Path]:
        boundary = candidate.resolve()
        for path in candidate.rglob("*"):
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                if not path.resolve().is_relative_to(boundary):
                    raise AgentKitError("Ссылка project-skills выходит за пределы candidate")
        skills_root = candidate / "skills"
        if not skills_root.is_dir():
            raise AgentKitError("В project-skills отсутствует каталог skills/")
        skills: dict[str, Path] = {}
        for skill in sorted(skills_root.iterdir()):
            if not skill.is_dir():
                continue
            document = skill / "SKILL.md"
            if not document.is_file():
                raise AgentKitError(f"Отсутствует SKILL.md: {skill.name}")
            identifier = markdown_frontmatter(document).get("name")
            if not isinstance(identifier, str) or not identifier:
                raise AgentKitError(f"Отсутствует строковое имя skill: {skill.name}")
            if identifier in skills:
                raise AgentKitError(f"Повторяющийся skill id: {identifier}")
            if identifier != skill.name:
                raise AgentKitError(f"Имя skill не совпадает с каталогом: {skill.name}")
            skills[identifier] = skill
        if not skills:
            raise AgentKitError("В project-skills нет дочерних каталогов skills")
        return skills

    def _validate_candidate(self, candidate: Path) -> tuple[dict[str, Path], list[dict[str, Any]]]:
        evidence: list[dict[str, Any]] = []
        try:
            skills = self._structure(candidate)
        except (AgentKitError, OSError, UnicodeError, RuntimeError) as error:
            evidence.append({"check": "structure", "status": "FAIL", "reason": redact_url(str(error))})
            return {}, evidence
        evidence.append({"check": "structure", "status": "PASS", "skills": sorted(skills)})
        accepted = True
        for identifier, path in skills.items():
            try:
                passed, checks = self.validator(path)
            except Exception as error:
                passed, checks = False, [{"check": "security", "status": "FAIL", "reason": str(error)}]
            evidence.append({"check": "security", "skill": identifier,
                             "status": "PASS" if passed else "FAIL", "evidence": _redacted(checks)})
            accepted = accepted and passed
        return skills if accepted else {}, evidence

    def _read_status(self, path: Path) -> ProjectSkillsStatus:
        value = load_json(path)
        if not isinstance(value.get("skills"), list):
            raise AgentKitError("Некорректный состав project-skills")
        try:
            status = ProjectSkillsStatus(**{key: value[key] for key in ProjectSkillsStatus.__dataclass_fields__})
            status = ProjectSkillsStatus(**{**status.__dict__, "skills": tuple(status.skills)})
        except (KeyError, TypeError) as error:
            raise AgentKitError("Некорректное состояние project-skills") from error
        if (status.project_id != self.project.identifier
                or not isinstance(status.state, str)
                or status.state not in {"ACTIVE", "STALE", "UPDATE_REJECTED", "NOT_CONFIGURED"}
                or any(item is not None and not isinstance(item, str) for item in (
                    status.source_url, status.default_branch, status.requested_branch, status.resolved_revision,
                    status.active_revision, status.reason, status.updated_at))
                or any(not isinstance(item, str) or item in {"", ".", ".."} or "/" in item or "\\" in item
                       for item in status.skills)
                or len(status.skills) != len(set(status.skills))):
            raise AgentKitError("Некорректное состояние project-skills")
        return status

    def _check_revision(self, root: Path, revision: str) -> None:
        gitfile = root / ".git"
        if (root.is_symlink() or not root.is_dir() or not gitfile.is_file() or gitfile.is_symlink()
                or getattr(root.lstat(), "st_file_attributes", 0) & 0x400):
            raise AgentKitError("Отсутствует безопасная ревизия project-skills")
        try:
            pointer = gitfile.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir: "):
                raise ValueError("gitfile")
            metadata = (root / pointer.removeprefix("gitdir: ")).resolve()
            backlink = Path((metadata / "gitdir").read_text(encoding="utf-8").strip())
            if (metadata.parent != self.checkout.resolve() / ".git/worktrees"
                    or backlink.resolve() != gitfile.resolve()):
                raise ValueError("worktree metadata")
        except (OSError, UnicodeError, ValueError) as error:
            raise AgentKitError("Ревизия project-skills не связана с managed worktree") from error
        if self._git(["-C", str(root), "rev-parse", "HEAD"]) != revision:
            raise AgentKitError("Ревизия project-skills не совпадает с сохранённым SHA")
        if self._git(["-C", str(root), "status", "--porcelain", "--untracked-files=all", "--ignored"]):
            raise AgentKitError("Ревизия project-skills изменена после проверки")

    def _active(self) -> ProjectSkillsStatus | None:
        self._check_storage()
        pointer = self.root / "active.json"
        if not pointer.exists():
            return None
        active = self._read_status(pointer)
        revision = active.active_revision
        if (active.state != "ACTIVE" or not revision or not re.fullmatch(r"[0-9a-f]{40,64}", revision)
                or active.resolved_revision != revision or not active.skills):
            raise AgentKitError("Некорректный active pointer project-skills")
        root = self.root / "revisions" / revision
        self._check_revision(root, revision)
        try:
            skills = self._structure(root)
        except (OSError, UnicodeError, RuntimeError) as error:
            raise AgentKitError("Некорректная активная ревизия project-skills") from error
        if tuple(skills) != active.skills:
            raise AgentKitError("Состав активных project-skills не совпадает с active pointer")
        return active

    def active_skills(self) -> dict[str, Path]:
        if self.project.skills_repository is None:
            return {}
        active = self._active()
        if active is None:
            return {}
        return {identifier: self.root / "revisions" / active.active_revision / "skills" / identifier
                for identifier in active.skills}

    def status(self) -> ProjectSkillsStatus:
        if self.project.skills_repository is None:
            return self._not_configured()
        active = self._active()
        if (self.root / "status.json").is_file():
            try:
                recorded = self._read_status(self.root / "status.json")
            except (AgentKitError, UnicodeError):
                if active is None:
                    raise
                return active
            if (active and recorded.active_revision == active.active_revision and recorded.skills == active.skills
                    and recorded.state in {"ACTIVE", "STALE", "UPDATE_REJECTED"}):
                return recorded
            if (active is None and recorded.active_revision is None and not recorded.skills
                    and recorded.state in {"STALE", "UPDATE_REJECTED"}):
                return recorded
        if active:
            return active
        raise AgentKitError("Project-skills ещё не синхронизированы")

    def _record(self, status: ProjectSkillsStatus, evidence: list[dict[str, Any]]) -> None:
        atomic_write(self.root / "status.json", json.dumps(_redacted({**status.as_dict(), "evidence": evidence}),
                                                          ensure_ascii=False, indent=2) + "\n")

    def resync(self, ci: bool = False) -> ProjectSkillsStatus:
        if self.project.skills_repository is None:
            return self._not_configured()
        self._check_storage()
        with _repository_lock(self.lock_path):
            active = self._active()
            source = self.source()
            branch: str | None = None
            revision: str | None = None
            candidate: Path | None = None
            evidence: list[dict[str, Any]] = []
            state: Literal["STALE", "UPDATE_REJECTED"] = "STALE"
            try:
                branch = self.requested_branch(ci=ci)
                candidate, revision = self._fetch_candidate(ci=ci)
                state = "UPDATE_REJECTED"
                skills, evidence = self._validate_candidate(candidate)
                if not skills:
                    raise AgentKitError("Candidate project-skills отклонён проверкой структуры или безопасности")
                if active and revision == active.active_revision:
                    self._discard_candidate(candidate)
                    candidate = None
                    # Та же ревизия сохраняет исходное время и atomic pointer.
                    if (active.requested_branch == branch and active.source_url == redact_url(source.url)
                            and active.default_branch == source.default_branch):
                        self._record(active, evidence)
                        return active
                destination = self.root / "revisions" / revision
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    self._check_revision(destination, revision)
                    if candidate is not None:
                        self._discard_candidate(candidate)
                        candidate = None
                else:
                    self._git(["-C", str(self.checkout), "worktree", "move", str(candidate), str(destination)])
                    candidate = None
                result = ProjectSkillsStatus(self.project.identifier, redact_url(source.url), source.default_branch,
                                             branch, revision, revision, "ACTIVE", None,
                                             datetime.now(timezone.utc).isoformat(), tuple(skills))
                self._record(result, evidence)
                atomic_write(self.root / "active.json", json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n")
                return result
            except (AgentKitError, OSError, UnicodeError) as error:
                result = ProjectSkillsStatus(self.project.identifier, redact_url(source.url), source.default_branch,
                                             branch, revision, active.active_revision if active else None, state,
                                             redact_url(str(error)), datetime.now(timezone.utc).isoformat(),
                                             active.skills if active else ())
                try:
                    self._record(result, evidence)
                except Exception:
                    # Неавторитетная диагностика не заменяет исходный результат
                    # и не раскрывает неотредактированную ошибку записи.
                    pass
                if active is None:
                    raise AgentKitError(result.reason) from None
                return result
            finally:
                if candidate is not None:
                    self._discard_candidate(candidate)
