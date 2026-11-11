from __future__ import annotations

from pathlib import Path

from agent_engineering_kit.profiles import compile_permission_profile, load_profiles, validate_profiles


REPOSITORY = Path(__file__).resolve().parents[1]


def test_default_profiles_are_valid_and_have_english_descriptions() -> None:
    result = validate_profiles(REPOSITORY)
    profiles = load_profiles(REPOSITORY)

    assert result.ok, [item.render() for item in result.diagnostics]
    assert {item["id"] for item in profiles} == {"developer", "tester", "reviewer"}
    assert all(item["description"].isascii() for item in profiles)


def test_default_profiles_expose_sdlc_roles_and_skills_without_broadening_permissions() -> None:
    profiles = {item["id"]: item for item in load_profiles(REPOSITORY)}

    assert profiles["developer"]["roles"] == [
        "orchestrator",
        "requirements-analyst",
        "architect",
        "developer",
        "reviewer",
    ]
    assert profiles["developer"]["skills"] == [
        "project-orientation",
        "codebase-analysis",
        "requirements-analysis",
        "architecture-decision",
        "change-impact",
        "test-design",
        "verification",
    ]
    assert profiles["developer"]["permissions"] == {
        "approval_mode": "custom",
        "sandbox": "workspace-write",
        "network": "allowlist",
        "tools": ["read", "search", "edit", "test", "git"],
    }

    assert profiles["reviewer"]["roles"] == ["reviewer", "security-engineer"]
    assert profiles["reviewer"]["skills"] == ["code-review", "change-impact", "threat-modeling"]
    assert profiles["reviewer"]["permissions"] == {
        "approval_mode": "readonly",
        "sandbox": "read-only",
        "network": "deny",
        "tools": ["read", "search", "test", "git-diff"],
    }

    assert profiles["tester"]["roles"] == [
        "orchestrator",
        "qa-engineer",
        "evaluation-engineer",
        "release-engineer",
    ]
    assert profiles["tester"]["skills"] == [
        "project-orientation",
        "test-design",
        "verification",
        "agent-evaluation",
        "release-readiness",
        "incident-analysis",
    ]
    assert profiles["tester"]["permissions"] == {
        "approval_mode": "readonly",
        "sandbox": "read-only",
        "network": "deny",
        "tools": ["read", "search", "test"],
    }


def test_permission_profile_compiles_without_claiming_client_enforcement() -> None:
    compiled = compile_permission_profile(REPOSITORY, "developer", client_capabilities={"sandbox", "approvals"})

    assert compiled["profile"] == "developer"
    assert compiled["permissions"]["approval_mode"] == "custom"
    assert compiled["enforcement"]["sandbox"] == "client"
    assert compiled["enforcement"]["network"] == "unavailable"
