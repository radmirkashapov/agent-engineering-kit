"""Идемпотентная установка внешних средств и проверка безопасности skills."""

from __future__ import annotations

import json
import hashlib
import os
import platform
import re
import shutil
from pathlib import Path
from typing import Any, Callable

from .catalog import LockedComponent, resolve_desired
from .component_state import Lifecycle, read_state, write_state
from .io import atomic_write
from .paths import KitPaths, ensure_runtime
from .process import CommandResult, run_command
from .result import ValidationResult


Runner = Callable[..., CommandResult]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SecurityToolManager:
    def __init__(self, repository: Path, paths: KitPaths, *, runner: Runner = run_command) -> None:
        self.repository = repository
        self.paths = paths
        self.runner = runner

    def desired(self) -> list[tuple[dict[str, Any], LockedComponent]]:
        return resolve_desired(self.repository, "security")

    def tool_root(self, identifier: str) -> Path:
        return self.paths.installations / "security" / identifier

    def executable(self, item: dict[str, Any]) -> Path | None:
        root_candidate = self.tool_root(item["id"]) / "bin" / item["command"]
        if platform.system() == "Windows":
            windows_candidate = root_candidate.with_suffix(".exe")
            if windows_candidate.is_file():
                return windows_candidate
        if root_candidate.is_file():
            return root_candidate
        return None

    def status(self) -> list[dict[str, Any]]:
        values = []
        for item, lock in self.desired():
            state = read_state(self.paths, "security", item["id"])
            executable = self.executable(item)
            status = state.get("status", Lifecycle.NOT_INSTALLED.value)
            if not executable:
                status = Lifecycle.NOT_INSTALLED.value
            elif state.get("revision") != lock.revision:
                status = Lifecycle.OUTDATED.value
            elif state.get("status") == Lifecycle.ACTIVE.value:
                expected_digest = state.get("executable_sha256")
                if not expected_digest:
                    status = Lifecycle.OUTDATED.value
                elif _sha256(executable) != expected_digest:
                    status = Lifecycle.ERROR.value
            values.append({**state, "id": item["id"], "required": item.get("required", False), "status": status, "executable": str(executable) if executable else None, "desired_revision": lock.revision})
        return values

    def _verify_version(self, item: dict[str, Any], executable: Path, expected: str) -> tuple[bool, str]:
        """Проверить именно установленную версию, включая Go binaries без release ldflags."""
        if item["installation"]["type"] == "go-install":
            completed = self.runner(["go", "version", "-m", str(executable)])
            output = completed.stdout + completed.stderr
            tokens = output.replace("\t", " ").split()
            return completed.ok and expected in tokens, output
        completed = self.runner([str(executable), "--version"])
        output = completed.stdout + completed.stderr
        expected_number = expected.lstrip("v")
        versions = {match.lstrip("vV") for match in re.findall(r"[vV]?\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.-]+)?", output)}
        return completed.ok and expected_number in versions, output

    def install(self, *, force: bool = False) -> ValidationResult:
        ensure_runtime(self.paths)
        result = ValidationResult()
        for item, lock in self.desired():
            identifier = item["id"]
            current = read_state(self.paths, "security", identifier)
            current_executable = self.executable(item)
            if current_executable and current.get("revision") == lock.revision and not force:
                version_ok, _ = self._verify_version(item, current_executable, lock.version)
                digest_ok = current.get("executable_sha256") == _sha256(current_executable)
                if version_ok and digest_ok:
                    result.info("security-install", f"{identifier}: уже установлен и проверен, revision {lock.revision[:12]}")
                    continue
            if platform.system().lower() not in item.get("platforms", []):
                write_state(self.paths, "security", identifier, Lifecycle.NOT_SUPPORTED, revision=lock.revision)
                severity = "error" if item.get("required") else "warning"
                getattr(result, severity)("security-install", f"{identifier}: platform не поддерживается")
                continue
            root = self.tool_root(identifier)
            (root / "bin").mkdir(parents=True, exist_ok=True)
            install = item["installation"]
            if install["type"] == "uv-tool":
                environment = {
                    "UV_TOOL_DIR": str(root / "tool"),
                    "UV_TOOL_BIN_DIR": str(root / "bin"),
                }
                command = [
                    "uv", "tool", "install", "--force", "--python", str(install.get("python", "3.13")),
                    install["requirement"].replace("{revision}", lock.revision),
                ]
            elif install["type"] == "go-install":
                environment = {"GOBIN": str(root / "bin")}
                command = ["go", "install", install["module"].replace("{version}", lock.version)]
            else:
                result.error("security-install", f"{identifier}: неизвестный installation.type")
                continue
            write_state(self.paths, "security", identifier, Lifecycle.INSTALLED, revision=lock.revision, installation_path=str(root))
            completed = self.runner(command, env=environment)
            executable = self.executable(item)
            version_ok, version_output = self._verify_version(item, executable, lock.version) if executable else (False, "executable отсутствует")
            if not completed.ok or not executable or not version_ok:
                reason = (completed.stderr or completed.stdout or version_output)[-2000:]
                write_state(self.paths, "security", identifier, Lifecycle.ERROR, revision=lock.revision, reason=reason)
                result.error("security-install", f"{identifier}: installation/version verification завершилась ошибкой")
                continue
            write_state(
                self.paths,
                "security",
                identifier,
                Lifecycle.ACTIVE,
                revision=lock.revision,
                version=lock.version,
                installation_path=str(root),
                executable=str(executable),
                executable_sha256=_sha256(executable),
                version_evidence=version_output.strip()[:500],
            )
            result.info("security-install", f"{identifier}: ACTIVE {lock.version}")
        return result

    def validation_environment(self) -> dict[str, str]:
        bins = [str(self.tool_root(item["id"]) / "bin") for item, _ in self.desired()]
        environment = {"PATH": os.pathsep.join([*bins, os.environ.get("PATH", "")])}
        by_id = {item["id"]: self.executable(item) for item, _ in self.desired()}
        if by_id.get("semgrep"):
            environment["SKILLEVALUATOR_SEMGREP_PATH"] = str(by_id["semgrep"])
        if by_id.get("skillspector"):
            environment["SKILLEVALUATOR_SKILLSPECTOR_PATH"] = str(by_id["skillspector"])
        return environment

    def validate_skill(self, skill_root: Path) -> tuple[bool, list[dict[str, Any]]]:
        desired = {item["id"]: item for item, _ in self.desired()}
        evidence: list[dict[str, Any]] = []
        required = ("skill-evaluator", "skillspector", "semgrep", "gitleaks")
        status_by_id = {item["id"]: item for item in self.status()}
        missing = [identifier for identifier in required if status_by_id.get(identifier, {}).get("status") != Lifecycle.ACTIVE.value]
        if missing:
            return False, [{"check": "security-tools", "status": "INCOMPLETE", "missing_or_unverified": missing}]

        evaluator = self.executable(desired["skill-evaluator"])
        head_result = self.runner(["git", "rev-parse", "HEAD"], cwd=skill_root)
        revision = head_result.stdout.strip() if head_result.ok else "unknown"
        target = skill_root / "skills" if (skill_root / "skills").is_dir() else skill_root
        report_dir = self.paths.state / "reports" / "skills" / revision
        if report_dir.exists():
            shutil.rmtree(report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        completed = self.runner(
            [
                str(evaluator), "validate", str(target), "--type", "skill",
                "--checks", "security,pii,license,code-integrity,unicode,dependency",
                "--no-dedup", "-r", "cli", "-o", str(report_dir),
            ],
            env=self.validation_environment(),
        )
        output = completed.stdout + completed.stderr
        accepted = False
        active_review: dict[str, Any] = {}
        finding_codes = sorted(set(re.findall(r"\(([A-Z]{1,3}\d+)\)", output)))
        summary_path = report_dir / "catalog-summary.json"
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            summary = {}
        for item, lock in resolve_desired(self.repository, "skills"):
            review = item.get("security", {})
            accepted_codes = set(review.get("accepted_finding_codes", []))
            expected_count = len(item.get("capabilities", []))
            reports_complete = (
                completed.returncode == 1
                and bool(finding_codes)
                and summary.get("total") == expected_count
                and summary.get("failed") == expected_count
                and all((report_dir / capability / "BENCHMARK.md").is_file() for capability in item.get("capabilities", []))
            )
            if reports_complete and lock.revision == revision == review.get("reviewed_revision") and set(finding_codes) <= accepted_codes and "SECURITY-CRITICAL" not in output:
                accepted = True
                active_review = review
                break

        gitleaks = self.executable(desired["gitleaks"])
        leaks_report = report_dir / "gitleaks.json"
        if leaks_report.exists():
            leaks_report.unlink()
        leaks = self.runner([str(gitleaks), "dir", str(skill_root), "--redact", "--no-banner", "--report-format", "json", "--report-path", str(leaks_report)])
        leak_findings = json.loads(leaks_report.read_text(encoding="utf-8")) if leaks_report.is_file() else []
        reviewed_leaks = {(item["rule"], item["path"], item["line"]) for item in active_review.get("accepted_gitleaks", [])}
        actual_leaks = set()
        for finding in leak_findings:
            path = Path(finding["File"])
            try:
                relative = path.resolve().relative_to(skill_root.resolve()).as_posix()
            except ValueError:
                relative = path.as_posix()
            actual_leaks.add((finding["RuleID"], relative, finding["StartLine"]))
        leaks_reviewed = bool(actual_leaks) and actual_leaks <= reviewed_leaks and accepted
        leaks_ok = leaks.ok or leaks_reviewed
        evidence.append({
            "check": "SkillEvaluator+SkillSpector+Semgrep+instruction-collision",
            "status": "PASS" if completed.ok and leaks_ok else ("PASS_WITH_REVIEWED_FINDINGS" if accepted and leaks_ok else "FAIL"),
            "exit_code": completed.returncode,
            "finding_codes": finding_codes,
            "reviewed_finding_codes": finding_codes if accepted else [],
            "report_path": str(report_dir),
            "output": output[-4000:],
        })
        evidence.append({"check": "Gitleaks current tree", "status": "PASS" if leaks.ok else ("PASS_WITH_REVIEWED_FINDINGS" if leaks_reviewed else "FAIL"), "reviewed_findings": sorted(actual_leaks) if leaks_reviewed else [], "output": (leaks.stdout + leaks.stderr)[-2000:]})
        return (completed.ok or accepted) and leaks_ok, evidence

    def scan(self, target: Path, *, skill_roots: list[Path]) -> tuple[bool, dict[str, Any]]:
        """Запустить локальную инвентаризацию проекта и статическую проверку effective skills."""
        target = target.expanduser().resolve()
        if not target.is_dir():
            report = {"version": 1, "status": "FAIL", "checks": [], "error": f"Каталог не существует: {target}"}
            return False, report
        ensure_runtime(self.paths)
        desired = {item["id"]: item for item, _ in self.desired()}
        status_by_id = {item["id"]: item for item in self.status()}
        required = ("bumblebee", "skillspector")
        missing = [
            identifier
            for identifier in required
            if status_by_id.get(identifier, {}).get("status") != Lifecycle.ACTIVE.value
        ]
        report_root = self.paths.state / "reports" / "security" / hashlib.sha256(str(target).encode()).hexdigest()[:16]
        report_root.mkdir(parents=True, exist_ok=True)
        report_path = report_root / "scan.json"
        checks: list[dict[str, Any]] = []
        if missing:
            checks.append({"check": "security-tools", "status": "FAIL", "missing_or_unverified": missing})
        else:
            bumblebee = self.executable(desired["bumblebee"])
            inventory = self.runner([
                str(bumblebee), "scan", "--profile", "project", "--root", str(target),
            ])
            checks.append({
                "check": "Bumblebee project inventory",
                "status": "PASS" if inventory.ok else "FAIL",
                "exit_code": inventory.returncode,
                "output": (inventory.stdout + inventory.stderr)[-8000:],
            })
            skillspector = self.executable(desired["skillspector"])
            for index, skill_root in enumerate(sorted({path.expanduser().resolve() for path in skill_roots})):
                output_path = report_root / f"skillspector-{index + 1}.json"
                completed = self.runner([
                    str(skillspector), "scan", str(skill_root), "--no-llm",
                    "--format", "json", "--output", str(output_path),
                ])
                checks.append({
                    "check": "SkillSpector static skill scan",
                    "target": str(skill_root),
                    "status": "PASS" if completed.ok else "FAIL",
                    "exit_code": completed.returncode,
                    "output": (completed.stdout + completed.stderr)[-4000:],
                    "details_path": str(output_path) if output_path.is_file() else None,
                })
        ok = bool(checks) and all(check["status"] == "PASS" for check in checks)
        report = {
            "version": 1,
            "target": str(target),
            "status": "PASS" if ok else "FAIL",
            "checks": checks,
            "report_path": str(report_path),
        }
        atomic_write(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return ok, report

    def doctor(self) -> ValidationResult:
        result = ValidationResult()
        for state in self.status():
            message = f"{state['id']}: {state['status']}"
            if state["status"] == Lifecycle.ACTIVE.value:
                result.info("security-doctor", message)
            elif state.get("required"):
                result.error("security-doctor", message)
            else:
                result.warning("security-doctor", message)
        return result
