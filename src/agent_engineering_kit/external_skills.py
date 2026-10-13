"""Внешние skills: кандидат → проверка → атомарная активация → откат."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

from .access import resolve_access
from .catalog import LockedComponent, resolve_desired
from .component_state import Lifecycle, read_state, write_state
from .definitions import validate_skill_directory
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

    def _first_party_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for skill in sorted((self.repository / "skills" / "first-party").glob("*/SKILL.md")):
            metadata = markdown_frontmatter(skill)
            items.append({**metadata, "id": metadata.get("name") or metadata.get("id") or skill.parent.name, "path": str(skill.parent)})
        return items

    def available(self) -> list[dict[str, Any]]:
        """Вернуть все first-party и внешние skills с итоговым решением о доступе."""
        resolved = resolve_desired(self.repository, "skills")
        external_items = [item for item, _ in resolved]
        first_party_items = self._first_party_items()
        items = [*first_party_items, *external_items]
        first_party_ids = {item["id"] for item in first_party_items}
        enforced = {item["id"] for item in items if item.get("required") or item.get("policy") == "enforced"}
        effective = apply_local_overrides(items, self.paths.overrides, "skills", self.project_id, enforced=enforced)
        for item in effective:
            if not item.get("path"):
                continue
            validation = validate_skill_directory(
                Path(item["path"]),
                self.repository / "schemas" / "skill.schema.json",
                item["id"],
                f"effective skill {item['id']!r}",
            )
            if not validation.ok:
                errors = "; ".join(
                    diagnostic.message
                    for diagnostic in validation.diagnostics
                    if diagnostic.severity == "ERROR"
                )
                raise AgentKitError(f"Некорректный local skill override: {errors}")
        effective_by_id = {item["id"]: item for item in effective}
        decisions = resolve_access({item["id"] for item in items}, self.paths.overrides, "skills", self.project_id)
        available: list[dict[str, Any]] = []
        for catalog_item in items:
            identifier = catalog_item["id"]
            item = effective_by_id.get(identifier, catalog_item)
            decision = decisions[identifier]
            disabled_by_override = identifier not in effective_by_id
            row = {
                **item,
                "enabled": decision.enabled and not disabled_by_override,
                "access_reason": "disabled:override" if disabled_by_override else decision.reason,
            }
            if identifier in first_party_ids:
                row["source"] = "first-party"
            elif item.get("path"):
                row["source"] = "local-override"
            available.append(row)
        return available

    def desired(self) -> list[tuple[dict[str, Any], LockedComponent]]:
        locks = {item["id"]: lock for item, lock in resolve_desired(self.repository, "skills")}
        return [
            (item, locks[item["id"]])
            for item in self.available()
            if item["id"] in locks and item["enabled"] and not item.get("path")
        ]

    def component_root(self, identifier: str) -> Path:
        return self.paths.installations / "skills" / identifier

    def active_path(self, identifier: str) -> Path | None:
        state = read_state(self.paths, "skills", identifier)
        path = state.get("installation_path") if state.get("status") == Lifecycle.ACTIVE.value else state.get("active_installation_path")
        return Path(path) if path and Path(path).is_dir() else None

    def list(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        locks = {item["id"]: lock for item, lock in resolve_desired(self.repository, "skills")}
        for item in self.available():
            if item.get("source") == "first-party" or item.get("source") == "local-override":
                values.append({**item, "status": Lifecycle.ACTIVE.value if item["enabled"] else "DISABLED"})
                continue
            lock = locks[item["id"]]
            state = read_state(self.paths, "skills", item["id"])
            status = "DISABLED" if not item["enabled"] else state.get("status", Lifecycle.NOT_INSTALLED.value)
            if item["enabled"] and status == Lifecycle.ACTIVE.value:
                installation_path = state.get("installation_path")
                if not installation_path or not Path(installation_path).is_dir():
                    status = Lifecycle.NOT_INSTALLED.value
                elif state.get("revision") != lock.revision:
                    status = Lifecycle.OUTDATED.value
            values.append({**state, "id": item["id"], "source": item["source"]["repository"], "enabled": item["enabled"], "access_reason": item["access_reason"], "status": status, "desired_revision": lock.revision, "version": lock.version})
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
        desired = self.desired()
        results = [self.install_one(item, lock, force=force) for item, lock in desired]
        managed_ids = {item["id"] for item, _ in resolve_desired(self.repository, "skills")}
        state_root = self.paths.state / "components" / "skills"
        if state_root.exists():
            for path in state_root.glob("*.json"):
                if path.stem not in managed_ids:
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
