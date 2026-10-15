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


def test_permission_profile_compiles_without_claiming_client_enforcement() -> None:
    compiled = compile_permission_profile(REPOSITORY, "developer", client_capabilities={"sandbox", "approvals"})

    assert compiled["profile"] == "developer"
    assert compiled["permissions"]["approval_mode"] == "custom"
    assert compiled["enforcement"]["sandbox"] == "client"
    assert compiled["enforcement"]["network"] == "unavailable"
