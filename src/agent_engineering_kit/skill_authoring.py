"""Авторинг skills в пользовательских checkout."""

from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .definitions import is_english_text, validate_skill_directory
from .errors import AgentKitError
from .io import atomic_write, markdown_frontmatter
from .paths import resolve_paths
from .process import run_command
from .project_skills import _GIT_STATE_ENVIRONMENT, _repository_lock, redact_url
from .projects import LogicalProject


@dataclass(frozen=True)
class _Skill:
    identifier: str
    description: str


def _entry_mode(path: Path) -> int | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise AgentKitError(f"Недопустимый symlink: {path}")
    return info.st_mode


def _directory(path: Path, *, optional: bool = False) -> bool:
    mode = _entry_mode(path)
    if mode is None and optional:
        return False
    if mode is None or not stat.S_ISDIR(mode):
        raise AgentKitError(f"Ожидался обычный каталог: {path}")
    return True


def _directory_path(path: Path, *, optional: bool = False) -> Path:
    path = path.expanduser().absolute()
    for parent in reversed(path.parents):
        _directory(parent, optional=optional)
    _directory(path, optional=optional)
    return path.resolve()


def _regular_tree(root: Path) -> None:
    _directory(root)
    for entry in root.iterdir():
        if entry.name.lower() == ".git":
            raise AgentKitError(f"Каталог skill содержит Git metadata (.git): {entry}")
        mode = _entry_mode(entry)
        if mode is not None and stat.S_ISDIR(mode):
            _regular_tree(entry)
        elif mode is None or not stat.S_ISREG(mode):
            raise AgentKitError(f"Ожидался обычный файл skill: {entry}")


def _validated_skill(repository: Path, directory: Path, identifier: str | None = None) -> _Skill:
    _regular_tree(directory)
    skill_file = directory / "SKILL.md"
    if not skill_file.is_file():
        raise AgentKitError(f"Отсутствует обычный файл SKILL.md: {directory}")
    try:
        metadata = markdown_frontmatter(skill_file)
    except UnicodeError as error:
        raise AgentKitError(f"Не удалось прочитать SKILL.md: {directory}: {error}") from None
    if identifier is None:
        identifier = metadata.get("name")
    if not isinstance(identifier, str) or re.fullmatch(r"[a-z][a-z0-9-]*", identifier) is None:
        raise AgentKitError(f"Некорректный skill ID: {identifier!r}")
    validation = validate_skill_directory(directory, repository / "schemas/skill.schema.json", identifier, str(directory))
    if not validation.ok:
        raise AgentKitError("\n".join(diagnostic.message for diagnostic in validation.diagnostics))
    return _Skill(identifier, metadata["description"])


def _validated_source(repository: Path, source: Path, identifier: str | None) -> tuple[Path, _Skill]:
    source = _directory_path(source)
    skill = _validated_skill(repository, source, identifier)
    if source.name != skill.identifier:
        raise AgentKitError(f"Имя каталога skill {source.name!r} должно совпадать с ID {skill.identifier!r}")
    return source, skill


def _validate_bundled_description(skill: _Skill) -> None:
    if not is_english_text(skill.description):
        raise AgentKitError(f"{skill.identifier}: default description должен быть на английском")


def _git(directory: Path, *args: str) -> str:
    if any(name in _GIT_STATE_ENVIRONMENT or name.startswith("GIT_CONFIG_") for name in os.environ):
        raise AgentKitError("Небезопасное окружение Git: очистите repository-local переменные")
    result = run_command(["git", "-C", str(directory), *args])
    if not result.ok:
        detail = redact_url((result.stderr or result.stdout).strip())
        raise AgentKitError(f"Ошибка Git authoring checkout: {detail}")
    return result.stdout.strip()


def _normal_checkout(checkout: Path) -> None:
    mode = _entry_mode(checkout / ".git")
    if mode is None or not stat.S_ISDIR(mode):
        raise AgentKitError(f"Ожидался обычный Git checkout: {checkout}")
    if Path(_git(checkout, "rev-parse", "--show-toplevel")).resolve() != checkout:
        raise AgentKitError(f"Ожидался корень Git checkout: {checkout}")


def _project_source(project: LogicalProject) -> tuple[str, str]:
    source = project.skills_repository or {}
    url = source.get("url")
    branch = source.get("default_branch", "main")
    if not isinstance(url, str) or not url.strip():
        raise AgentKitError("Настройте skills.repository в manifest или через project init")
    if not isinstance(branch, str) or not branch or branch.startswith("-") or "@{" in branch:
        raise AgentKitError("Некорректная ветка skills.repository")
    return url.strip(), branch


def _normalized_origin(url: str, relative_to: Path) -> str:
    url = url.strip()
    try:
        parts = urlsplit(url)
        if parts.scheme == "file" and parts.netloc.lower() in ("", "localhost") and not parts.query and not parts.fragment:
            path = unquote(parts.path)
            if os.name == "nt" and re.match(r"^/[a-zA-Z]:", path):
                path = path[1:]
            return str(Path(path).resolve())
        if "://" in url:
            authority = parts.netloc
            userinfo, separator, host = authority.rpartition("@")
            return parts._replace(netloc=userinfo + separator + host.lower(), path=parts.path.rstrip("/")).geturl()
    except ValueError:
        raise AgentKitError("Некорректный URL skills.repository или origin") from None
    if not Path(url).is_absolute() and re.match(r"^[^/\\:]+:", url):
        return url.rstrip("/")
    return str((relative_to / url).resolve())


def _inside_directory(path: Path, root: Path) -> bool:
    if path.is_relative_to(root):
        return True
    try:
        root_info = root.stat()
    except FileNotFoundError:
        return False
    for candidate in (path, *path.parents):
        try:
            if os.path.samestat(candidate.stat(), root_info):
                return True
        except FileNotFoundError:
            continue
    return False


def _check_destination(path: Path, project: LogicalProject, *, include_descendants: bool = False) -> None:
    def conflicts_with(root: Path) -> bool:
        return _inside_directory(path, root) or (include_descendants and _inside_directory(root, path))

    if conflicts_with(resolve_paths().data):
        raise AgentKitError(f"Путь authoring пересекается с managed-хранилищем: {path}")
    for repository in project.manifest.get("repositories", []):
        root = (project.root / repository["path"]).resolve()
        git_root = next((path for path in (root, *root.parents) if os.path.lexists(path / ".git")), root)
        if conflicts_with(git_root):
            raise AgentKitError(f"Путь authoring пересекается с product repository: {path}")


def _authoring_checkout(checkout: Path, project: LogicalProject) -> Path:
    checkout = _directory_path(checkout)
    _check_destination(checkout, project)
    url, _ = _project_source(project)
    _normal_checkout(checkout)
    origin = _git(checkout, "config", "--null", "--get-all", "remote.origin.url").split("\0", 1)[0]
    if _normalized_origin(origin, checkout) != _normalized_origin(url, project.root):
        raise AgentKitError("Git origin checkout должен совпадать с skills.repository.url")
    return checkout


def checkout_project_skills(project: LogicalProject, destination: Path) -> Path:
    url, branch = _project_source(project)
    destination = _directory_path(destination, optional=True)
    _check_destination(destination, project)
    if destination.exists() and any(destination.iterdir()):
        raise AgentKitError(f"Clone требует пустой (empty) каталог: {destination}")
    if _git(project.root, "check-ref-format", "--branch", branch) != branch:
        raise AgentKitError("Некорректная ветка skills.repository")
    _git(project.root, "-c", "protocol.ext.allow=never", "clone", "--branch", branch, "--", url, str(destination))
    return destination


def _check_replacement(checkout: Path, target: Path, replace: bool) -> bool:
    if not _directory(target, optional=True):
        return False
    if not replace:
        raise AgentKitError(f"Каталог skill уже существует: {target}. Укажите --replace для замены.")
    _regular_tree(target)
    relative = target.relative_to(checkout).as_posix()
    tracked = _git(checkout, "ls-files", "--", f"{relative}/SKILL.md")
    if not tracked:
        raise AgentKitError(f"Замена требует tracked SKILL.md: {target}")
    # ls-files -v uses a lowercase tag for assume-unchanged and S for skip-worktree.
    entries = _git(checkout, "ls-files", "-v", "-z", "--", relative).split("\0")
    if any(entry and (entry[0].islower() or entry[0] == "S") for entry in entries):
        raise AgentKitError(f"Замена требует снять флаги assume-unchanged и skip-worktree: {target}")
    dirty = _git(checkout, "status", "--porcelain", "--untracked-files=all")
    ignored_at_target = _git(checkout, "ls-files", "--others", "--ignored", "--exclude-standard", "--", relative)
    if dirty or ignored_at_target:
        raise AgentKitError(f"Замена требует clean Git checkout: сохраните изменения в {checkout}")
    return True


@contextmanager
def _copy_skill(
    repository: Path,
    source: Path,
    target: Path,
    *,
    replace_existing: bool,
    require_english_description: bool = False,
) -> Iterator[_Skill]:
    if target.is_relative_to(source) or source.is_relative_to(target):
        raise AgentKitError("Исходный каталог и destination skill пересекаются")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    staged = temporary / "skill"
    previous = temporary / "previous"
    published = False
    backed_up = False
    preserve_backup = False
    try:
        shutil.copytree(source, staged, symlinks=True)
        copied = _validated_skill(repository, staged, target.name)
        if require_english_description:
            _validate_bundled_description(copied)
        if replace_existing:
            os.replace(target, previous)
            backed_up = True
        os.replace(staged, target)
        published = True
        yield copied
    except BaseException:
        try:
            if published:
                os.replace(target, staged)
            if backed_up:
                os.replace(previous, target)
        except OSError as error:
            preserve_backup = True
            raise AgentKitError(f"Не удалось восстановить skill из {temporary}: {error}") from error
        raise
    finally:
        if not preserve_backup:
            with suppress(OSError):
                shutil.rmtree(temporary)


def add_bundled_skill(
    repository: Path, source: Path, *, identifier: str | None = None, replace: bool = False,
) -> Path:
    repository = _directory_path(repository)
    source, skill = _validated_source(repository, source, identifier)
    _validate_bundled_description(skill)
    target = _directory_path(repository / "skills" / "first-party" / skill.identifier, optional=True)
    exists = _check_replacement(repository, target, replace)
    try:
        with _copy_skill(repository, source, target, replace_existing=exists, require_english_description=True):
            return target
    except OSError as error:
        raise AgentKitError(f"Не удалось скопировать skill: {error}") from error


def _index_target(checkout: Path, project: LogicalProject) -> Path:
    skills_root = checkout / "skills"
    _directory(skills_root, optional=True)
    # Every package target and temporary directory is a descendant of this write root.
    _check_destination(skills_root, project, include_descendants=True)
    target = skills_root / "INDEX.md"
    mode = _entry_mode(target)
    if mode is not None and not stat.S_ISREG(mode):
        raise AgentKitError(f"Ожидался обычный файл индекса skills: {target}")
    return target


def _indexed_skills(repository: Path, skills_root: Path, *, skip: Path | None = None) -> list[_Skill]:
    if not skills_root.exists():
        return []
    skills = []
    for path in sorted(skills_root.iterdir()):
        if path == skip:
            continue
        mode = _entry_mode(path)
        if mode is not None and stat.S_ISDIR(mode) and _entry_mode(path / "SKILL.md") is not None:
            skills.append(_validated_skill(repository, path, path.name))
    return skills


def _write_index(target: Path, skills: list[_Skill]) -> Path:
    rows = ["# Project skills", "", "| ID | Назначение | Определение |", "|---|---|---|"]
    for skill in sorted(skills, key=lambda skill: skill.identifier):
        description = " ".join(skill.description.split()).replace("\\", "\\\\").replace("|", "\\|")
        rows.append(f"| `{skill.identifier}` | {description} | `{skill.identifier}/SKILL.md` |")
    atomic_write(target, "\n".join(rows) + "\n")
    return target


@contextmanager
def _project_authoring_lock(checkout: Path) -> Iterator[None]:
    path = checkout / ".git" / "agent-kit-skill-authoring.lock"
    mode = _entry_mode(path)
    if mode is not None and not stat.S_ISREG(mode):
        raise AgentKitError(f"Ожидался обычный файл блокировки: {path}")
    try:
        with _repository_lock(path):
            yield
    except OSError as error:
        raise AgentKitError(f"Не удалось обновить project skills: {error}") from error


def add_project_skill(
    repository: Path,
    project: LogicalProject,
    source: Path,
    checkout: Path,
    *,
    identifier: str | None = None,
    replace: bool = False,
) -> Path:
    checkout = _authoring_checkout(checkout, project)
    source, skill = _validated_source(repository, source, identifier)
    with _project_authoring_lock(checkout):
        index = _index_target(checkout, project)
        target = index.parent / skill.identifier
        exists = _check_replacement(checkout, target, replace)
        skills = _indexed_skills(repository, index.parent, skip=target)
        with _copy_skill(repository, source, target, replace_existing=exists) as copied:
            _write_index(index, [*skills, copied])
    return target


def write_project_skill_index(
    repository: Path, checkout: Path, *, project: LogicalProject,
) -> Path:
    checkout = _authoring_checkout(checkout, project)
    with _project_authoring_lock(checkout):
        index = _index_target(checkout, project)
        return _write_index(index, _indexed_skills(repository, index.parent))
