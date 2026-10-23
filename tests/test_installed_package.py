from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]


def _installed_wheel(tmp_path: Path) -> Path:
    wheel_directory = tmp_path / "wheel"
    wheel_directory.mkdir()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(wheel_directory),
            str(REPOSITORY),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    wheel = next(wheel_directory.glob("agent_engineering_kit-*.whl"))
    installed = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(installed)
    return installed


def _checkout_with_access_schema(root: Path, version: int) -> Path:
    checkout = root
    schema = checkout / "schemas/access.schema.json"
    schema.parent.mkdir(parents=True)
    schema.write_text(
        json.dumps({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["version"],
            "properties": {"version": {"const": version}},
        }),
        encoding="utf-8",
    )
    return checkout


def _validate_access_from_installed_wheel(installed: Path, data: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "AGENT_KIT_DATA_HOME": str(data),
        "PYTHONPATH": str(installed),
    }
    environment.pop("AGENT_KIT_REPOSITORY", None)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from agent_engineering_kit.access import validate_access; "
                "from agent_engineering_kit.paths import resolve_paths; "
                "paths=resolve_paths(); "
                "result=validate_access({'mcp': {'sentry'}, 'skills': set()}, paths.overrides); "
                "raise SystemExit(0 if result.ok else 2)"
            ),
        ],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_installed_wheel_reads_access_schema_from_registered_checkout(tmp_path: Path) -> None:
    installed = _installed_wheel(tmp_path)
    checkout = _checkout_with_access_schema(tmp_path / "checkout", version=1)
    data = tmp_path / "data"
    pointer = data / "state/repository-path"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(f"{checkout}\n", encoding="utf-8")
    access = data / "overrides/global/access.yaml"
    access.parent.mkdir(parents=True)
    access.write_text("version: 1\nmcp:\n  allow: []\n  block: []\n", encoding="utf-8")

    completed = _validate_access_from_installed_wheel(installed, data, tmp_path)

    assert completed.returncode == 0, completed.stderr


def test_new_process_uses_schema_from_replaced_checkout_pointer(tmp_path: Path) -> None:
    installed = _installed_wheel(tmp_path)
    checkout_a = _checkout_with_access_schema(tmp_path / "checkout-a", version=1)
    checkout_b = _checkout_with_access_schema(tmp_path / "checkout-b", version=2)
    data = tmp_path / "data"
    pointer = data / "state/repository-path"
    pointer.parent.mkdir(parents=True)
    access = data / "overrides/global/access.yaml"
    access.parent.mkdir(parents=True)
    access.write_text("version: 1\nmcp:\n  allow: []\n  block: []\n", encoding="utf-8")

    pointer.write_text(f"{checkout_a}\n", encoding="utf-8")
    first = _validate_access_from_installed_wheel(installed, data, tmp_path)
    pointer.write_text(f"{checkout_b}\n", encoding="utf-8")
    second = _validate_access_from_installed_wheel(installed, data, tmp_path)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 2, second.stderr


def test_explicit_repository_overrides_registered_checkout(tmp_path: Path) -> None:
    installed = _installed_wheel(tmp_path)
    registered = _checkout_with_access_schema(tmp_path / "registered", version=2)
    explicit = _checkout_with_access_schema(tmp_path / "explicit", version=1)
    data = tmp_path / "data"
    pointer = data / "state/repository-path"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(f"{registered}\n", encoding="utf-8")
    access = data / "overrides/global/access.yaml"
    access.parent.mkdir(parents=True)
    access.write_text("version: 1\nmcp:\n  allow: []\n  block: []\n", encoding="utf-8")
    environment = {
        **os.environ,
        "AGENT_KIT_DATA_HOME": str(data),
        "AGENT_KIT_REPOSITORY": str(explicit),
        "PYTHONPATH": str(installed),
    }

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from agent_engineering_kit.access import validate_access; "
                "from agent_engineering_kit.paths import resolve_paths; "
                "paths=resolve_paths(); "
                "result=validate_access({'mcp': set(), 'skills': set()}, paths.overrides); "
                "raise SystemExit(0 if result.ok else 2)"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
