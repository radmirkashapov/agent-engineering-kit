"""Запуск дочерних процессов без подстановки командной оболочки и утечки окружения."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run_command(args: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> CommandResult:
    effective_env = dict(os.environ)
    if env:
        effective_env.update(env)
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            env=effective_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        return CommandResult(tuple(args), 127, "", str(error))
    return CommandResult(tuple(args), completed.returncode, completed.stdout, completed.stderr)
