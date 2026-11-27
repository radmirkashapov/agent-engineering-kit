"""Обновление памяти после Git-событий без отмены пользовательского коммита."""

import hashlib
import json
import subprocess
import sys
import os
from pathlib import Path

from .io import atomic_write
from .process import run_command


MARKER = '# agent-engineering-kit:memory'


def install_memory_hooks(root: Path):
    result = run_command(['git', '-C', str(root), 'rev-parse', '--git-path', 'hooks'])
    if not result.ok:
        return []
    directory = Path(result.stdout.strip())
    if not directory.is_absolute():
        directory = root / directory
    generated = []
    for name in ('post-commit', 'post-checkout', 'post-merge'):
        target = directory / name
        if target.exists() and MARKER not in target.read_text(encoding='utf-8', errors='replace'):
            # Чужой hook не изменяем: session preflight остаётся резервным путём.
            continue
        atomic_write(target, '#!/bin/sh\n' + MARKER + '\nagent-kit project memory-event >/dev/null 2>&1 || true\n')
        target.chmod(target.stat().st_mode | 0o111)
        generated.append(target)
    return generated


def enqueue(project, paths):
    key = hashlib.sha256(str(project.root).encode()).hexdigest()[:16]
    target = paths.projects / project.identifier / 'state' / f'memory-pending-{key}.json'
    # Изменения без коммита учитываются по содержимому diff, а не только HEAD.
    from .bindings import repository_paths
    fingerprint = hashlib.sha256()
    for root in repository_paths(project, paths).values():
        for arguments in (['rev-parse', 'HEAD'], ['diff', 'HEAD'], ['status', '--porcelain']):
            observed = run_command(['git', '-C', str(root), *arguments])
            fingerprint.update(str(root).encode())
            fingerprint.update(observed.stdout.encode())
        listing = run_command(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'])
        for relative in listing.stdout.split('\0'):
            if not relative:
                continue
            try:
                stat = (root / relative).lstat()
                fingerprint.update(f'{relative}:{stat.st_size}:{stat.st_mtime_ns}'.encode())
            except FileNotFoundError:
                fingerprint.update(f'{relative}:missing'.encode())
    revision = fingerprint.hexdigest()
    result_path = target.with_name(f'memory-result-{key}.json')
    if result_path.is_file():
        previous = json.loads(result_path.read_text())
        if previous.get('fingerprint') == revision and previous.get('status') == 'PASS':
            return
    atomic_write(target, json.dumps({'root': str(project.root), 'fingerprint': revision}))
    environment = {**os.environ, 'AGENT_KIT_DATA_HOME': str(paths.data), 'AGENT_KIT_REPOSITORY': str(paths.repository)}
    try:
        subprocess.Popen([sys.executable, '-m', 'agent_engineering_kit.memory_events', str(project.root)], env=environment,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError as error:
        atomic_write(result_path, json.dumps({'status': 'FAIL', 'error': str(error), 'fingerprint': revision}))


def refresh(root: Path):
    from .paths import resolve_paths
    from .projects import find_project
    from .project_memory import ProjectMemoryManager
    from .project_skills import _repository_lock
    paths = resolve_paths()
    project = find_project(root)
    if project is None:
        return
    key = hashlib.sha256(str(project.root).encode()).hexdigest()[:16]
    target = paths.projects / project.identifier / 'state' / f'memory-pending-{key}.json'
    with _repository_lock(paths.locks / f'memory-{key}.lock'):
        # Очистить событие до запуска: событие во время индексации останется pending.
        while target.is_file():
            claimed = target.with_suffix('.running')
            try:
                os.replace(target, claimed)
            except FileNotFoundError:
                continue
            event = json.loads(claimed.read_text())
            claimed.unlink()
            try:
                report = ProjectMemoryManager(paths.repository, paths).index(project, mode='refresh')
            except Exception as error:
                report = {'status': 'FAIL', 'error': str(error)}
            atomic_write(target.with_name(f'memory-result-{key}.json'), json.dumps({**report, 'fingerprint': event['fingerprint']}, ensure_ascii=False))


if __name__ == '__main__':
    refresh(Path(sys.argv[1]))
