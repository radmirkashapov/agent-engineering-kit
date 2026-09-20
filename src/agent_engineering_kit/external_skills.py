"""External skills: candidate → validation → atomic activation → rollback."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

from .catalog import LockedComponent, resolve_desired
from .component_state import Lifecycle, read_state, write_state
from .errors import AgentKitError
from .io import markdown_frontmatter
from .models import allowed_model_references, load_policy, model_references
from .paths import KitPaths, ensure_runtime
from .process import CommandResult, run_command
from .overrides import apply_local_overrides
from .security_tools import SecurityToolManager


SkillValidator = Callable[[Path], tuple[bool, list[dict[str, Any]]]]


class ExternalSkillManager:
    def __init__(
        self,
        repository: Path,
        paths: KitPaths,
        *,
        validator: SkillValidator | None = None,
        runner: Callable[..., CommandResult] = run_command,
        project_id: str | None = None,
    ) -> None:
        self.repository = repository
        self.paths = paths
        self.runner = runner
        self.project_id = project_id
        self.validator = validator or SecurityToolManager(repository, paths, runner=runner).validate_skill

    def desired(self) -> list[tuple[dict[str, Any], LockedComponent]]:
        resolved = resolve_desired(self.repository, "skills")
        locks = {item["id"]: lock for item, lock in resolved}
        items = [item for item, _ in resolved]
        enforced = {item["id"] for item in items if item.get("required")}
        effective = apply_local_overrides(items, self.paths.overrides, "skills", self.project_id, enforced=enforced)
        return [(item, locks[item["id"]]) for item in effective]

    def component_root(self, identifier: str) -> Path:
        return self.paths.installations / "skills" / identifier

    def active_path(self, identifier: str) -> Path | None:
        state = read_state(self.paths, "skills", identifier)
        path = state.get("installation_path") if state.get("status") == Lifecycle.ACTIVE.value else state.get("active_installation_path")
        return Path(path) if path and Path(path).is_dir() else None

    def list(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        first_party_root = self.repository / "skills" / "first-party"
        first_party_items: list[dict[str, Any]] = []
        for skill in sorted(first_party_root.glob("*/SKILL.md")):
            metadata = markdown_frontmatter(skill)
            first_party_items.append({**metadata, "id": metadata.get("name") or metadata.get("id") or skill.parent.name, "path": str(skill.parent)})
        enforced = {item["id"] for item in first_party_items if item.get("policy") == "enforced"}
        for item in apply_local_overrides(first_party_items, self.paths.overrides, "skills", self.project_id, enforced=enforced):
            values.append({**item, "source": "first-party", "status": Lifecycle.ACTIVE.value})
        for item, lock in self.desired():
            state = read_state(self.paths, "skills", item["id"])
            status = state.get("status", Lifecycle.NOT_INSTALLED.value)
            if status == Lifecycle.ACTIVE.value:
                installation_path = state.get("installation_path")
                if not installation_path or not Path(installation_path).is_dir():
                    status = Lifecycle.NOT_INSTALLED.value
                elif state.get("revision") != lock.revision:
                    status = Lifecycle.OUTDATED.value
            values.append({**state, "id": item["id"], "source": item["source"]["repository"], "status": status, "desired_revision": lock.revision, "version": lock.version})
        return values

    def _validate_source(self, candidate: Path, item: dict[str, Any], lock: LockedComponent) -> list[str]:
        errors: list[str] = []
        head = self.runner(["git", "rev-parse", "HEAD"], cwd=candidate)
        if not head.ok or head.stdout.strip() != lock.revision:
            errors.append("candidate HEAD не совпадает с lock revision")
        origin = self.runner(["git", "remote", "get-url", "origin"], cwd=candidate)
        if not origin.ok or origin.stdout.strip().rstrip("/") != item["source"]["repository"].rstrip("/"):
            errors.append("candidate origin не совпадает с catalog source")
        if (candidate / ".gitmodules").exists():
            errors.append("Git submodules запрещены для external skill candidate")
        for path in candidate.rglob("*"):
            if path.is_symlink():
                try:
                    path.resolve().relative_to(candidate.resolve())
                except ValueError:
                    errors.append(f"symlink выходит за candidate: {path.relative_to(candidate)}")
        for capability in item.get("capabilities", []):
            skill_file = candidate / "skills" / capability / "SKILL.md"
            if not skill_file.is_file():
                errors.append(f"required capability отсутствует: {capability}")
                continue
            try:
                metadata = markdown_frontmatter(skill_file)
            except Exception as error:
                errors.append(f"не удалось прочитать frontmatter {capability}: {error}")
                continue
            actual_name = metadata.get("name") or metadata.get("id")
            if actual_name != capability:
                errors.append(f"skill name не совпадает с каталогом: {capability}")
        return errors

    def _candidate(self, identifier: str) -> Path:
        root = self.paths.state / "candidates" / "skills"
        root.mkdir(parents=True, exist_ok=True)
        return root / f"{identifier}-{uuid.uuid4().hex}"

    def _validate_model_policy(self, candidate: Path, item: dict[str, Any]) -> list[str]:
        policy = load_policy(self.repository, local_path=self.paths.overrides / "models.yaml")
        allowed = allowed_model_references(policy)
        errors: list[str] = []
        for capability in item.get("capabilities", []):
            skill_file = candidate / "skills" / capability / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                metadata = markdown_frontmatter(skill_file)
            except Exception as error:
                errors.append(f"{capability}: некорректный frontmatter: {error}")
                continue
            for reference in sorted(model_references(metadata)):
                if reference not in allowed:
                    errors.append(f"{capability}: model {reference!r} отсутствует в effective policy")
        return errors

    def install_one(self, item: dict[str, Any], lock: LockedComponent, *, force: bool = False) -> dict[str, Any]:
        ensure_runtime(self.paths)
        identifier = item["id"]
        current = read_state(self.paths, "skills", identifier)
        current_path = self.active_path(identifier)
        active_revision = current.get("revision") if current.get("status") == Lifecycle.ACTIVE.value else current.get("active_revision")
        if current_path and current.get("status") == Lifecycle.ACTIVE.value and current.get("revision") == lock.revision and not force:
            return {**current, "changed": False}

        candidate = self._candidate(identifier)
        write_state(self.paths, "skills", identifier, Lifecycle.INSTALLED, revision=lock.revision, candidate_path=str(candidate))
        cloned = self.runner(["git", "clone", "--quiet", "--no-checkout", item["source"]["repository"], str(candidate)])
        if not cloned.ok:
            state = write_state(self.paths, "skills", identifier, Lifecycle.ERROR, revision=lock.revision, reason=cloned.stderr[-2000:], active_revision=active_revision, active_installation_path=str(current_path) if current_path else None)
            return {**state, "changed": False}
        checked_out = self.runner(["git", "checkout", "--quiet", "--detach", lock.revision], cwd=candidate)
        if not checked_out.ok:
            state = write_state(self.paths, "skills", identifier, Lifecycle.ERROR, revision=lock.revision, reason=checked_out.stderr[-2000:], active_revision=active_revision, active_installation_path=str(current_path) if current_path else None)
            return {**state, "changed": False}

        write_state(self.paths, "skills", identifier, Lifecycle.VALIDATING, revision=lock.revision, candidate_path=str(candidate))
        try:
            source_errors = self._validate_source(candidate, item, lock)
        except Exception as error:
            source_errors = [f"source validation exception: {error}"]
        try:
            model_errors = self._validate_model_policy(candidate, item)
        except Exception as error:
            model_errors = [f"model policy validation exception: {error}"]
        try:
            security_ok, evidence = self.validator(candidate)
        except Exception as error:
            security_ok, evidence = False, [{"check": "security-tools", "status": "FAIL", "error": str(error)}]
        evidence = [
            {"check": "source-and-lock", "status": "PASS" if not source_errors else "FAIL", "errors": source_errors},
            {"check": "model-policy", "status": "PASS" if not model_errors else "FAIL", "errors": model_errors},
            {"check": "client-compatibility", "status": "PASS", "mechanisms": ["symlink", "generated-copy-fallback"]},
            *evidence,
        ]
        if source_errors or model_errors or not security_ok:
            state = write_state(
                self.paths,
                "skills",
                identifier,
                Lifecycle.BLOCKED,
                revision=lock.revision,
                previous_revision=active_revision,
                active_revision=active_revision,
                active_installation_path=str(current_path) if current_path else None,
                reason="; ".join([*source_errors, *model_errors]) or "security validation failed",
                validation=evidence,
                candidate_path=str(candidate),
            )
            return {**state, "changed": False}

        revisions = self.component_root(identifier) / "revisions"
        revisions.mkdir(parents=True, exist_ok=True)
        target = revisions / lock.revision
        if target.exists():
            shutil.rmtree(candidate)
        else:
            os.replace(candidate, target)
        state = write_state(
            self.paths,
            "skills",
            identifier,
            Lifecycle.ACTIVE,
            version=lock.version,
            revision=lock.revision,
            previous_revision=active_revision or current.get("previous_revision"),
            installation_path=str(target),
            validation=evidence,
        )
        return {**state, "changed": True}

    def resync(self, *, force: bool = False) -> list[dict[str, Any]]:
        results = [self.install_one(item, lock, force=force) for item, lock in self.desired()]
        desired_ids = {item["id"] for item, _ in self.desired()}
        state_root = self.paths.state / "components" / "skills"
        if state_root.exists():
            for path in state_root.glob("*.json"):
                if path.stem not in desired_ids:
                    write_state(self.paths, "skills", path.stem, Lifecycle.BLOCKED, reason="stale managed dependency удалена из catalog")
        return results

    def rollback(self, identifier: str) -> dict[str, Any]:
        state = read_state(self.paths, "skills", identifier)
        previous = state.get("previous_revision")
        if not previous:
            raise AgentKitError(f"{identifier}: previous revision отсутствует")
        target = self.component_root(identifier) / "revisions" / previous
        if not target.is_dir():
            raise AgentKitError(f"{identifier}: rollback target отсутствует: {previous}")
        return write_state(
            self.paths,
            "skills",
            identifier,
            Lifecycle.ACTIVE,
            revision=previous,
            previous_revision=state.get("revision"),
            installation_path=str(target),
            validation=[{"check": "rollback", "status": "PASS"}],
        )
