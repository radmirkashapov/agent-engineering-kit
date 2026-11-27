from pathlib import Path
import json

import pytest

from agent_engineering_kit.local_runtime import model_enforcement, set_model_enforcement, portable_content
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.clients import sync_clients
from agent_engineering_kit.conventions import load_conventions
from agent_engineering_kit.io import atomic_write
from agent_engineering_kit.memory_events import install_memory_hooks


def kit_paths(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    return KitPaths(repo, tmp_path, tmp_path/'runtime', tmp_path/'projects', tmp_path/'overrides')


def test_model_mode_is_local_and_project_layer_wins(tmp_path):
    paths = kit_paths(tmp_path)
    assert model_enforcement(paths)
    set_model_enforcement(paths.overrides/'global', False)
    assert not model_enforcement(paths, 'demo')
    set_model_enforcement(paths.overrides/'projects/demo', True)
    assert model_enforcement(paths, 'demo')
    assert not model_enforcement(paths, 'other')


def test_model_projection_preserves_original_and_capabilities(tmp_path):
    paths = kit_paths(tmp_path)
    original = (paths.repository/'skills/first-party/code-review/SKILL.md').read_bytes()
    set_model_enforcement(paths.overrides/'global', False)
    sync_clients(paths.repository, paths)
    target = paths.installations/'clients/shared/skills/code-review/SKILL.md'
    assert not target.is_symlink()
    assert 'model_capabilities:' in target.read_text()
    assert (paths.repository/'skills/first-party/code-review/SKILL.md').read_bytes() == original
    assert 'model:' not in portable_content('---\nname: test\nmodel:\n  allowed: [corporate]\nrequires:\n  model_capabilities: [reasoning]\n---\nBody')


def test_convention_can_be_disabled_locally(tmp_path):
    paths = kit_paths(tmp_path)
    baseline = load_conventions(paths.repository)
    identifier = baseline[0]['id']
    atomic_write(paths.overrides/'global/conventions/test.yaml', f'target: {identifier}\noverride:\n  mode: disable\n')
    assert identifier not in {item['id'] for item in load_conventions(paths.repository, paths=paths)}
    assert identifier in {item['id'] for item in load_conventions(paths.repository)}


def test_project_publication_does_not_overwrite_another_project(tmp_path):
    paths = kit_paths(tmp_path)
    sync_clients(paths.repository, paths, project_id='first')
    policy = paths.installations/'clients/projects/first/effective-policy.json'
    before = policy.read_bytes()
    sync_clients(paths.repository, paths, project_id='second')
    assert policy.read_bytes() == before


def test_read_rejects_different_or_nested_project(tmp_path, monkeypatch, capsys):
    from agent_engineering_kit.cli import run
    from agent_engineering_kit.io import atomic_write
    root = tmp_path/'child'
    root.mkdir()
    atomic_write(root/'.ai-team/project.yaml', 'version: 1\nid: child\nname: child\n')
    monkeypatch.chdir(root)
    assert run(['skills', 'read', 'code-review', '--project-id', 'parent']) == 1
    assert 'не относится' in capsys.readouterr().err


def test_memory_hooks_preserve_user_hook(tmp_path):
    import subprocess
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    hook = tmp_path/'.git/hooks/post-commit'
    hook.write_text('#!/bin/sh\necho user\n')
    generated = install_memory_hooks(tmp_path)
    assert hook.read_text() == '#!/bin/sh\necho user\n'
    assert {path.name for path in generated} == {'post-checkout', 'post-merge'}


def test_background_worker_records_failure_without_raising(tmp_path, monkeypatch):
    from agent_engineering_kit import memory_events
    from agent_engineering_kit import paths as path_module, projects, project_memory
    from types import SimpleNamespace
    import hashlib
    paths = kit_paths(tmp_path)
    project = SimpleNamespace(root=tmp_path, identifier='demo')
    key = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:16]
    pending = paths.projects/'demo/state'/f'memory-pending-{key}.json'
    atomic_write(pending, json.dumps({'fingerprint': 'abc'}))
    monkeypatch.setattr(path_module, 'resolve_paths', lambda: paths)
    monkeypatch.setattr(projects, 'find_project', lambda _: project)
    def fail(*args, **kwargs):
        raise RuntimeError('index unavailable')
    monkeypatch.setattr(project_memory.ProjectMemoryManager, 'index', fail)
    memory_events.refresh(tmp_path)
    result = json.loads(pending.with_name(f'memory-result-{key}.json').read_text())
    assert result['status'] == 'FAIL'
    assert result['fingerprint'] == 'abc'
    assert not pending.exists()


def test_cli_model_switch_and_selection(tmp_path, monkeypatch, capsys):
    from agent_engineering_kit.cli import run
    paths = kit_paths(tmp_path)
    monkeypatch.setenv('AGENT_KIT_DATA_HOME', str(paths.data))
    monkeypatch.setenv('AGENT_KIT_REPOSITORY', str(paths.repository))
    assert run(['models', 'enforcement', 'off']) == 0
    assert not model_enforcement(paths)
    assert run(['override', 'select', 'agents', '--allow', 'reviewer', '--scope', 'global']) == 0
    sync_clients(paths.repository, paths)
    effective = json.loads((paths.installations/'clients/shared/effective-policy.json').read_text())
    assert [item['id'] for item in effective['agents']] == ['reviewer']


def test_pending_update_preserves_runtime_paths(tmp_path, monkeypatch):
    from agent_engineering_kit import memory_events
    from types import SimpleNamespace
    from agent_engineering_kit import bindings
    paths = kit_paths(tmp_path)
    launched = []
    monkeypatch.setattr(memory_events.subprocess, 'Popen', lambda *a, **kw: launched.append(kw))
    monkeypatch.setattr(bindings, 'repository_paths', lambda *args: {})
    memory_events.enqueue(SimpleNamespace(root=tmp_path, identifier='demo'), paths)
    assert launched[0]['env']['AGENT_KIT_DATA_HOME'] == str(paths.data)
    assert launched[0]['env']['AGENT_KIT_REPOSITORY'] == str(paths.repository)


def test_explicit_source_selection_is_resettable(tmp_path, monkeypatch):
    from agent_engineering_kit.cli import run
    paths = kit_paths(tmp_path)
    monkeypatch.setenv('AGENT_KIT_DATA_HOME', str(paths.data))
    monkeypatch.setenv('AGENT_KIT_REPOSITORY', str(paths.repository))
    assert run(['skills', 'prefer', 'code-review', '--source', 'built-in', '--scope', 'global']) == 0
    selection = paths.overrides/'global/skill-sources/code-review.yaml'
    assert selection.is_file()
    assert run(['skills', 'reset', 'code-review', '--scope', 'global']) == 0
    assert not selection.exists()
