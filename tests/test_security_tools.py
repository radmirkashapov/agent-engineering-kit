from __future__ import annotations

from pathlib import Path

import yaml

from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.process import CommandResult
from agent_engineering_kit.component_state import Lifecycle, write_state
from agent_engineering_kit.security_tools import SecurityToolManager, _sha256


def test_scanner_crash_is_not_accepted_as_reviewed_findings(tmp_path: Path) -> None:
    repository = tmp_path / "kit"
    (repository / "catalog").mkdir(parents=True)
    (repository / "locks").mkdir()
    revision = "a" * 40
    tools = [
        {"id": "skill-evaluator", "command": "skill-evaluator"},
        {"id": "skillspector", "command": "skillspector"},
        {"id": "semgrep", "command": "semgrep"},
        {"id": "gitleaks", "command": "gitleaks"},
    ]
    catalog = {
        "version": 1,
        "security": [
            {
                **tool,
                "required": True,
                "platforms": ["darwin", "linux", "windows"],
                "installation": {"type": "uv-tool", "requirement": "unused"},
            }
            for tool in tools
        ],
    }
    locks = {"version": 1, "components": [{"id": tool["id"], "version": "1", "revision": revision} for tool in tools]}
    skills = {
        "version": 1,
        "skills": [
            {
                "id": "fixture",
                "source": {"type": "git", "repository": "https://example.invalid/fixture.git"},
                "installation": {"mode": "external"},
                "required": True,
                "capabilities": ["example"],
                "security": {"reviewed_revision": revision, "accepted_finding_codes": ["E1"]},
            },
        ],
    }
    (repository / "catalog/security.yaml").write_text(yaml.safe_dump(catalog), encoding="utf-8")
    (repository / "locks/security.lock.yaml").write_text(yaml.safe_dump(locks), encoding="utf-8")
    (repository / "catalog/skills.yaml").write_text(yaml.safe_dump(skills), encoding="utf-8")
    (repository / "locks/skills.lock.yaml").write_text(
        yaml.safe_dump({"version": 1, "components": [{"id": "fixture", "version": "1", "revision": revision}]}),
        encoding="utf-8",
    )
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    for tool in tools:
        executable = paths.installations / "security" / tool["id"] / "bin" / tool["command"]
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.touch()
        write_state(
            paths,
            "security",
            tool["id"],
            Lifecycle.ACTIVE,
            revision=revision,
            executable_sha256=_sha256(executable),
        )

    skill_root = tmp_path / "candidate"
    (skill_root / "skills/example").mkdir(parents=True)

    def runner(args, **kwargs):
        if list(args[:3]) == ["git", "rev-parse", "HEAD"]:
            return CommandResult(tuple(args), 0, revision + "\n", "")
        if Path(args[0]).name == "gitleaks":
            return CommandResult(tuple(args), 0, "", "")
        return CommandResult(tuple(args), 1, "", "scanner crashed before producing reports")

    ok, evidence = SecurityToolManager(repository, paths, runner=runner).validate_skill(skill_root)

    assert ok is False
    assert evidence[0]["status"] == "FAIL"

    evaluator = paths.installations / "security/skill-evaluator/bin/skill-evaluator"
    evaluator.write_bytes(b"replaced")
    ok, evidence = SecurityToolManager(repository, paths, runner=runner).validate_skill(skill_root)
    assert ok is False
    assert "skill-evaluator" in evidence[0]["missing_or_unverified"]


def test_go_tool_version_uses_embedded_module_metadata(tmp_path: Path) -> None:
    repository = tmp_path / "kit"
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    executable = tmp_path / "gitleaks"
    executable.touch()

    def runner(args, **kwargs):
        assert args == ["go", "version", "-m", str(executable)]
        return CommandResult(tuple(args), 0, f"{executable}: go1.26\n\tmod\texample.invalid/tool\tv8.30.1\th1:test\n", "")

    manager = SecurityToolManager(repository, paths, runner=runner)
    verified, evidence = manager._verify_version(
        {"installation": {"type": "go-install"}},
        executable,
        "v8.30.1",
    )

    assert verified is True
    assert "v8.30.1" in evidence


def test_status_detects_replaced_managed_binary(tmp_path: Path) -> None:
    repository = tmp_path / "kit"
    (repository / "catalog").mkdir(parents=True)
    (repository / "locks").mkdir()
    revision = "b" * 40
    item = {
        "id": "scanner",
        "command": "scanner",
        "required": True,
        "platforms": ["darwin", "linux", "windows"],
        "installation": {"type": "uv-tool", "requirement": "unused"},
    }
    (repository / "catalog/security.yaml").write_text(
        yaml.safe_dump({"version": 1, "security": [item]}), encoding="utf-8"
    )
    (repository / "locks/security.lock.yaml").write_text(
        yaml.safe_dump({"version": 1, "components": [{"id": "scanner", "version": "1.0.0", "revision": revision}]}),
        encoding="utf-8",
    )
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    executable = data / "installations/security/scanner/bin/scanner"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"approved")
    write_state(
        paths,
        "security",
        "scanner",
        Lifecycle.ACTIVE,
        revision=revision,
        executable_sha256=_sha256(executable),
    )
    executable.write_bytes(b"replaced")

    assert SecurityToolManager(repository, paths).status()[0]["status"] == Lifecycle.ERROR.value
