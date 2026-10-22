from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess


REPOSITORY = Path(__file__).resolve().parents[1]


def test_posix_installer_registers_the_checkout_as_canonical_repository(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)
    data = tmp_path / "data"
    environment = {
        **os.environ,
        "AGENT_KIT_DATA_HOME": str(data),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
    }

    completed = subprocess.run(
        ["sh", "bootstrap/install.sh"],
        cwd=REPOSITORY,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (data / "state/repository-path").read_text(encoding="utf-8").strip() == str(REPOSITORY)
    assert completed.stdout.index("agent-kit resync --no-update") < completed.stdout.index("agent-kit validate --ci")


def test_posix_installer_rejects_zip_archive_without_git_metadata(tmp_path: Path) -> None:
    archive = tmp_path / "agent-engineering-kit-main"
    bootstrap = archive / "bootstrap"
    bootstrap.mkdir(parents=True)
    shutil.copy2(REPOSITORY / "bootstrap/install.sh", bootstrap / "install.sh")

    completed = subprocess.run(
        ["sh", "bootstrap/install.sh"],
        cwd=archive,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "полного Git checkout" in completed.stderr


def test_posix_installer_rejects_zip_nested_in_another_git_checkout(tmp_path: Path) -> None:
    foreign_checkout = tmp_path / "foreign"
    foreign_checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(foreign_checkout)], check=True)
    archive = foreign_checkout / "agent-engineering-kit-main"
    bootstrap = archive / "bootstrap"
    bootstrap.mkdir(parents=True)
    shutil.copy2(REPOSITORY / "bootstrap/install.sh", bootstrap / "install.sh")
    data = tmp_path / "data"

    completed = subprocess.run(
        ["sh", "bootstrap/install.sh"],
        cwd=archive,
        env={**os.environ, "AGENT_KIT_DATA_HOME": str(data)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "полного Git checkout" in completed.stderr
    assert not (data / "state/repository-path").exists()


def test_windows_installer_guards_git_root_and_failed_pip_before_pointer_write() -> None:
    script = (REPOSITORY / "bootstrap/install.ps1").read_text(encoding="utf-8")

    assert "if ($GitRoot -ne $Repository)" in script
    pip_position = script.index("python -m pip install --user $Repository")
    pip_guard_position = script.index('throw "Не удалось установить Python-пакет agent-kit.', pip_position)
    pointer_write_position = script.index("[System.IO.File]::WriteAllText")
    assert pip_position < pip_guard_position < pointer_write_position


def test_posix_installer_switches_registered_checkout(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)
    data = tmp_path / "data"
    environment = {
        **os.environ,
        "AGENT_KIT_DATA_HOME": str(data),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    checkouts: list[Path] = []
    for name in ("checkout-a", "checkout-b"):
        checkout = tmp_path / name
        bootstrap = checkout / "bootstrap"
        bootstrap.mkdir(parents=True)
        shutil.copy2(REPOSITORY / "bootstrap/install.sh", bootstrap / "install.sh")
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        checkouts.append(checkout)

    first = subprocess.run(
        ["sh", "bootstrap/install.sh"], cwd=checkouts[0], env=environment, check=False,
    )
    second = subprocess.run(
        ["sh", "bootstrap/install.sh"], cwd=checkouts[1], env=environment, check=False,
    )

    assert first.returncode == 0
    assert second.returncode == 0
    assert (data / "state/repository-path").read_text(encoding="utf-8").strip() == str(checkouts[1])
