from __future__ import annotations

from pathlib import Path
import re
import stat
import subprocess
import pytest

from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.definitions import is_english_text, validate_agents, validate_mcp, validate_skills
from agent_engineering_kit.validation import validate


@pytest.mark.parametrize("ci", [False, True])
def test_project_skills_validation_reports_default_without_remote_verification(tmp_path, monkeypatch, capsys, ci):
    from agent_engineering_kit.cli import run
    from conftest import write_yaml

    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    project = tmp_path / "product"
    write_yaml(project / ".ai-team/project.yaml", {
        "version": 1, "id": "ci-project", "name": "CI fixture",
        "repositories": [{"id": "app", "path": "."}],
        "documentation": {"index": "docs/INDEX.md", "roots": ["docs"]},
        "memory": {"namespace": "ci-project"},
        "skills": {"repository": {"url": "https://example.invalid/skills.git", "default_branch": "main"}},
    })
    override = data / "projects/ci-project/skills-repository/branch-override.json"
    override.parent.mkdir(parents=True)
    override.write_text('{"branch": "feat/machine-only"}')
    monkeypatch.chdir(project)
    monkeypatch.setenv("AGENT_KIT_REPOSITORY", str(repository))
    monkeypatch.setenv("AGENT_KIT_DATA_HOME", str(data))
    command = ["validate", "project-skills", *(["--ci"] if ci else [])]

    assert run(command) == 0
    output = capsys.readouterr().out
    assert "https://example.invalid/skills.git" in output
    assert ("feat/machine-only" if not ci else "main") in output
    assert "не разрешена" in output
    if ci:
        assert "feat/machine-only" not in output
        assert "user-local overrides отключены" in output
    assert not (override.parent / "checkout").exists()


@pytest.mark.parametrize("secret_url", [
    "https://manifest-user:manifest-password@example.invalid/skills.git?token=manifest-token#manifest-fragment",
    "https://manifest-user:manifest-password'part@example.invalid/skills.git",
    'https://manifest-user:manifest-password"part@example.invalid/skills.git',
    "https://example.invalid/skills.git?token='manifest-token part'",
    'https://example.invalid/skills.git#"manifest-fragment part"',
    "https://manifest-user: manifest-password'part@example.invalid/skills.git",
    "https://manifest-user:manifest-password 'part@example.invalid/skills.git",
])
def test_project_skills_validation_redacts_invalid_manifest_diagnostics(tmp_path, monkeypatch, secret_url):
    from conftest import write_yaml

    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    write_yaml(tmp_path / ".ai-team/project.yaml", {
        "id": "ci-project", "skills": {"repository": {"url": secret_url, "default_branch": "main"}},
    })
    monkeypatch.chdir(tmp_path)
    result = validate(repository, paths, "project-skills", include_local=False)
    assert not result.ok
    rendered = "\n".join(item.render() for item in result.diagnostics)
    assert all(secret not in rendered for secret in ("manifest-user", "manifest-password", "manifest-token", "manifest-fragment", "part"))


def test_repository_passes_ci_validation(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    gitleaks = paths.installations / "security/gitleaks/bin/gitleaks"
    gitleaks.parent.mkdir(parents=True)
    gitleaks.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    gitleaks.chmod(gitleaks.stat().st_mode | stat.S_IXUSR)
    result = validate(repository, paths, include_local=False)
    assert result.ok, "\n".join(item.render() for item in result.diagnostics)


def test_mcp_credential_template_covers_registry_environment_references() -> None:
    repository = Path(__file__).resolve().parents[1]
    result = validate_mcp(repository)
    assert result.ok, "\n".join(item.render() for item in result.diagnostics)


def test_mcp_validation_rejects_missing_specialized_credential_template(tmp_path: Path) -> None:
    from shutil import copytree

    repository = Path(__file__).resolve().parents[1]
    copytree(repository / "mcp", tmp_path / "mcp")
    copytree(repository / "schemas", tmp_path / "schemas")
    (tmp_path / ".env.example").write_text((repository / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")

    result = validate_mcp(tmp_path)

    assert not result.ok
    assert any("mcp-creds.example.env" in diagnostic.message for diagnostic in result.diagnostics)


def test_all_tracked_yaml_files_have_explanatory_comments() -> None:
    repository = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        ["git", "ls-files", "*.yaml", "*.yml"],
        cwd=repository,
        text=True,
        capture_output=True,
        check=True,
    )
    missing = []
    for name in completed.stdout.splitlines():
        lines = (repository / name).read_text(encoding="utf-8").splitlines()
        first_content = next((line.strip() for line in lines if line.strip()), "")
        comment = first_content.removeprefix("#").strip()
        if not first_content.startswith("#") or len(comment) < 20:
            missing.append(name)

    assert missing == [], f"YAML без содержательного вводного комментария: {missing}"


def test_user_facing_markdown_files_are_written_in_russian() -> None:
    repository = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.md"],
        cwd=repository,
        text=True,
        capture_output=True,
        check=True,
    )
    insufficient_russian = []
    for name in completed.stdout.splitlines():
        if name.startswith("agents/"):
            continue
        path = repository / name
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        prose: list[str] = []
        in_frontmatter = bool(lines and lines[0] == "---")
        in_code_fence = False
        for number, line in enumerate(lines):
            if in_frontmatter:
                if number > 0 and line == "---":
                    in_frontmatter = False
                continue
            if line.startswith("```"):
                in_code_fence = not in_code_fence
                continue
            if in_code_fence:
                continue
            without_code = re.sub(r"`[^`]*`", "", line)
            without_links = re.sub(r"\[[^]]*]\([^)]+\)", "", without_code)
            prose.append(without_links)

        text = "\n".join(prose)
        cyrillic = sum("А" <= character <= "я" or character in "Ёё" for character in text)
        latin = sum("A" <= character <= "Z" or "a" <= character <= "z" for character in text)
        russian_share = cyrillic / (cyrillic + latin) if cyrillic + latin else 0.0
        if cyrillic < 20 or russian_share < 0.7:
            insufficient_russian.append(f"{name} ({russian_share:.0%})")

    assert insufficient_russian == [], (
        f"Markdown без достаточной русскоязычной прозы: {insufficient_russian}"
    )


def test_default_agent_roles_are_complete_detailed_and_english() -> None:
    repository = Path(__file__).resolve().parents[1]

    result = validate_agents(repository)

    assert result.ok, "\n".join(item.render() for item in result.diagnostics)
    expected_roles = {
        "orchestrator",
        "requirements-analyst",
        "architect",
        "developer",
        "reviewer",
        "security-engineer",
        "qa-engineer",
        "evaluation-engineer",
        "release-engineer",
    }
    assert {path.stem for path in (repository / "agents").glob("*.md")} == expected_roles
    required_sections = (
        "## Mission",
        "## Use this role when",
        "## Required inputs",
        "## Responsibilities",
        "## Working method",
        "## Deliverables",
        "## Guardrails",
        "## Escalation and handoff",
        "## Completion criteria",
    )
    for path in (repository / "agents").glob("*.md"):
        content = path.read_text(encoding="utf-8")
        assert len(content.splitlines()) >= 45, f"Недостаточно подробная роль: {path.name}"
        assert not re.search(r"[А-Яа-яЁё]", content), f"Описание роли должно быть на английском: {path.name}"
        assert all(section in content for section in required_sections), path.name


def test_default_skill_and_mcp_descriptions_are_english() -> None:
    repository = Path(__file__).resolve().parents[1]

    skills = validate_skills(repository)
    mcp = validate_mcp(repository)

    assert skills.ok, "\n".join(item.render() for item in skills.diagnostics)
    assert mcp.ok, "\n".join(item.render() for item in mcp.diagnostics)


@pytest.mark.parametrize("field", ["source", "installation"])
def test_mcp_validation_rejects_url_credentials(tmp_path: Path, field: str) -> None:
    from shutil import copytree
    from agent_engineering_kit.io import load_yaml
    from conftest import write_yaml

    repository = Path(__file__).resolve().parents[1]
    copytree(repository / "mcp", tmp_path / "mcp")
    copytree(repository / "schemas", tmp_path / "schemas")
    (tmp_path / ".env.example").write_text((repository / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "mcp-creds.example.env").write_text((repository / "mcp-creds.example.env").read_text(encoding="utf-8"), encoding="utf-8")
    registry = load_yaml(tmp_path / "mcp" / "registry.yaml")
    target = registry["servers"][0][field]
    target["repository" if field == "source" else "endpoint"] = "https://operator:credential@example.com/mcp"
    write_yaml(tmp_path / "mcp" / "registry.yaml", registry)

    result = validate_mcp(tmp_path)

    assert not result.ok
    assert any("credentials" in diagnostic.message for diagnostic in result.diagnostics)


@pytest.mark.parametrize("suffix", ["?sig=secret", "?code=oauth-code", "#secret"])
def test_mcp_validation_rejects_query_and_fragment_urls(tmp_path: Path, suffix: str) -> None:
    from shutil import copytree
    from agent_engineering_kit.io import load_yaml
    from conftest import write_yaml

    repository = Path(__file__).resolve().parents[1]
    copytree(repository / "mcp", tmp_path / "mcp")
    copytree(repository / "schemas", tmp_path / "schemas")
    (tmp_path / ".env.example").write_text((repository / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "mcp-creds.example.env").write_text((repository / "mcp-creds.example.env").read_text(encoding="utf-8"), encoding="utf-8")
    registry = load_yaml(tmp_path / "mcp" / "registry.yaml")
    registry["servers"][0]["source"]["repository"] += suffix
    write_yaml(tmp_path / "mcp" / "registry.yaml", registry)

    result = validate_mcp(tmp_path)

    assert not result.ok
    assert any("credentials" in diagnostic.message for diagnostic in result.diagnostics)


def test_mcp_validation_requires_policy_for_every_registered_server(tmp_path: Path) -> None:
    from shutil import copytree
    from agent_engineering_kit.io import load_yaml
    from conftest import write_yaml

    repository = Path(__file__).resolve().parents[1]
    copytree(repository / "mcp", tmp_path / "mcp")
    copytree(repository / "schemas", tmp_path / "schemas")
    copytree(repository / "catalog" / "corporate", tmp_path / "catalog" / "corporate")
    (tmp_path / ".env.example").write_text((repository / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "mcp-creds.example.env").write_text((repository / "mcp-creds.example.env").read_text(encoding="utf-8"), encoding="utf-8")
    path = tmp_path / "catalog/corporate/mcp.yaml"
    catalog = load_yaml(path)
    catalog["servers"] = [entry for entry in catalog["servers"] if entry["id"] != "context7"]
    write_yaml(path, catalog)

    result = validate_mcp(tmp_path)

    assert not result.ok
    assert any("не имеет capability policy" in diagnostic.message for diagnostic in result.diagnostics)


def test_mcp_validation_rejects_unknown_access_profile_mode(tmp_path: Path) -> None:
    from shutil import copytree
    from agent_engineering_kit.io import load_yaml
    from conftest import write_yaml

    repository = Path(__file__).resolve().parents[1]
    copytree(repository / "mcp", tmp_path / "mcp")
    copytree(repository / "schemas", tmp_path / "schemas")
    copytree(repository / "catalog" / "corporate", tmp_path / "catalog" / "corporate")
    (tmp_path / ".env.example").write_text((repository / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "mcp-creds.example.env").write_text((repository / "mcp-creds.example.env").read_text(encoding="utf-8"), encoding="utf-8")
    path = tmp_path / "catalog" / "corporate" / "access-profiles.yaml"
    profiles = load_yaml(path)
    profiles["profiles"][0]["allowed_modes"] = ["destroy"]
    write_yaml(path, profiles)

    result = validate_mcp(tmp_path)

    assert not result.ok
    assert any("access profile" in diagnostic.message for diagnostic in result.diagnostics)


def test_mcp_validation_rejects_endpoint_outside_boundary(tmp_path: Path) -> None:
    from shutil import copytree
    from agent_engineering_kit.io import load_yaml
    from conftest import write_yaml

    repository = Path(__file__).resolve().parents[1]
    copytree(repository / "mcp", tmp_path / "mcp")
    copytree(repository / "schemas", tmp_path / "schemas")
    copytree(repository / "catalog" / "corporate", tmp_path / "catalog" / "corporate")
    (tmp_path / ".env.example").write_text((repository / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "mcp-creds.example.env").write_text((repository / "mcp-creds.example.env").read_text(encoding="utf-8"), encoding="utf-8")
    path = tmp_path / "catalog" / "corporate" / "mcp.yaml"
    catalog = load_yaml(path)
    next(entry for entry in catalog["servers"] if entry["id"] == "context7")["boundaries"]["allowed_hosts"] = ["unrelated.example"]
    write_yaml(path, catalog)

    result = validate_mcp(tmp_path)

    assert not result.ok
    assert any("allowed_hosts" in diagnostic.message for diagnostic in result.diagnostics)


def test_mcp_validation_rejects_write_on_read_only_server(tmp_path: Path) -> None:
    from shutil import copytree
    from agent_engineering_kit.io import load_yaml
    from conftest import write_yaml

    repository = Path(__file__).resolve().parents[1]
    copytree(repository / "mcp", tmp_path / "mcp")
    copytree(repository / "schemas", tmp_path / "schemas")
    copytree(repository / "catalog" / "corporate", tmp_path / "catalog" / "corporate")
    (tmp_path / ".env.example").write_text((repository / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "mcp-creds.example.env").write_text((repository / "mcp-creds.example.env").read_text(encoding="utf-8"), encoding="utf-8")
    path = tmp_path / "catalog" / "corporate" / "mcp.yaml"
    catalog = load_yaml(path)
    next(entry for entry in catalog["servers"] if entry["id"] == "context7")["capabilities"][0]["mode"] = "write"
    write_yaml(path, catalog)

    result = validate_mcp(tmp_path)

    assert not result.ok
    assert any("read_only" in diagnostic.message for diagnostic in result.diagnostics)


def test_mcp_validation_rejects_raw_corporate_logging(tmp_path: Path) -> None:
    from shutil import copytree
    from agent_engineering_kit.io import load_yaml
    from conftest import write_yaml

    repository = Path(__file__).resolve().parents[1]
    copytree(repository / "mcp", tmp_path / "mcp")
    copytree(repository / "schemas", tmp_path / "schemas")
    copytree(repository / "catalog" / "corporate", tmp_path / "catalog" / "corporate")
    (tmp_path / ".env.example").write_text((repository / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "mcp-creds.example.env").write_text((repository / "mcp-creds.example.env").read_text(encoding="utf-8"), encoding="utf-8")
    path = tmp_path / "catalog" / "corporate" / "data-classification.yaml"
    classes = load_yaml(path)
    classes["classes"][0]["logging"] = "raw"
    write_yaml(path, classes)

    result = validate_mcp(tmp_path)

    assert not result.ok
    assert any("logging" in diagnostic.message for diagnostic in result.diagnostics)


@pytest.mark.parametrize(
    "value",
    [
        "1234567890 -- 0987654321",
        "Describir capacidades y responsabilidades del sistema",
        "Describir a usuarios sistemas seguros y confiables",
        "Valider la configuration as service robuste et portable",
        "Analisar a configuração e as responsabilidades principais",
        "Validar a política e as configurações locais",
        "説明文として十分な長さを持つ文字列です",
    ],
)
def test_english_text_check_rejects_non_english_content(value: str) -> None:
    assert not is_english_text(value)
