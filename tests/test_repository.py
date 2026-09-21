from __future__ import annotations

from pathlib import Path
import re
import stat
import subprocess

from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.validation import validate


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


def test_all_markdown_files_are_written_in_russian() -> None:
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
        lines = (repository / name).read_text(encoding="utf-8").splitlines()
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
