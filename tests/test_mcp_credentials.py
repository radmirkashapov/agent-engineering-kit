from __future__ import annotations

import json
import os
import stat
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path

import pytest

import agent_engineering_kit.mcp_credentials as credentials_module
from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.mcp_credentials import credential_requirements, parse_credentials
from agent_engineering_kit.paths import KitPaths, ensure_runtime


def make_paths(tmp_path: Path) -> KitPaths:
    data = tmp_path / "data"
    return KitPaths(tmp_path / "repository", data, data / "runtime", data / "projects", data / "overrides")


def test_requirements_include_environment_references_and_required_names():
    servers = [{
        "id": "github",
        "environment": {"GITHUB_TOKEN": "env:GITHUB_PERSONAL_ACCESS_TOKEN"},
        "required_environment": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    }]
    requirements = credential_requirements(servers)
    assert list(requirements) == ["GITHUB_PERSONAL_ACCESS_TOKEN"]
    assert requirements["GITHUB_PERSONAL_ACCESS_TOKEN"].required_by == ("github",)
    assert requirements["GITHUB_PERSONAL_ACCESS_TOKEN"].optional_for == ()


def test_requirements_merge_sorted_required_and_optional_owners():
    requirements = credential_requirements(iter([
        {"id": "z", "environment": {"TOKEN": "env:SHARED", "PLAIN": "literal"}},
        {"id": "b", "required_environment": ["SHARED", "ONLY_REQUIRED"]},
        {"id": "a", "required_environment": ["SHARED"]},
        {"id": "z", "environment": {"ALIAS": "env:SHARED"}},
    ]))
    assert list(requirements) == ["ONLY_REQUIRED", "SHARED"]
    assert requirements["SHARED"].name == "SHARED"
    assert requirements["SHARED"].required_by == ("a", "b")
    assert requirements["SHARED"].optional_for == ("z",)
    assert requirements["ONLY_REQUIRED"].required_by == ("b",)


def test_parser_treats_input_as_data_and_preserves_equals_in_value():
    assert parse_credentials("TOKEN=a=b=c\n", allowed={"TOKEN"}) == {"TOKEN": "a=b=c"}


def test_parser_accepts_comments_empty_values_and_literal_spaces():
    assert parse_credentials("\n  # comment\r\nTOKEN= abc # def \r\nEMPTY=\n", allowed={"TOKEN", "EMPTY"}) == {
        "TOKEN": " abc # def ", "EMPTY": "",
    }
    assert parse_credentials("_TOKEN2=x\n", allowed=None) == {"_TOKEN2": "x"}


@pytest.mark.parametrize("content", [
    "export TOKEN=value\n",
    "TOKEN=$(whoami)\n",
    "TOKEN=${OTHER}\n",
    "TOKEN=`whoami`\n",
    "TOKEN=one\nTOKEN=two\n",
    "UNKNOWN=value\n",
    "BAD-NAME=value\n",
    "1TOKEN=value\n",
    "TOKEN value\n",
    "TOKEN =value\n",
    "TOKEN=value\x00\n",
])
def test_parser_rejects_unsafe_or_unknown_input_without_echoing_value(content):
    with pytest.raises(AgentKitError) as raised:
        parse_credentials(content, allowed={"TOKEN"})
    assert "value" not in str(raised.value)
    assert "whoami" not in str(raised.value)
    assert "строка" in str(raised.value).lower()


def test_parser_error_identifies_line_and_valid_variable_only():
    with pytest.raises(AgentKitError) as raised:
        parse_credentials("# comment\nTOKEN=${private-expansion}\n", allowed={"TOKEN"})
    message = str(raised.value)
    assert "2" in message
    assert "TOKEN" in message
    assert "private-expansion" not in message


def test_parser_invalid_name_is_not_echoed():
    with pytest.raises(AgentKitError) as raised:
        parse_credentials("private-secret!=x\n", allowed={"TOKEN"})
    assert "private-secret" not in str(raised.value)


def sample_servers():
    return [{
        "id": "sample",
        "environment": {"TOKEN": "env:TOKEN", "OPTIONAL": "env:OPTIONAL"},
        "required_environment": ["TOKEN"],
    }]


def test_import_is_atomic_private_and_status_never_contains_values(tmp_path):
    paths = make_paths(tmp_path)
    source = tmp_path / "mcp-creds.env"
    source.write_text("TOKEN=super-secret\nOPTIONAL=\n", encoding="utf-8")
    store = credentials_module.McpCredentialStore(paths)
    before = datetime.now(timezone.utc)
    target = store.import_file(source, iter(sample_servers()))
    after = datetime.now(timezone.utc)
    assert target == paths.data / "secrets" / "mcp-creds.env"
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    assert store.load() == {"OPTIONAL": "", "TOKEN": "super-secret"}
    rows = store.status(iter(sample_servers()))
    assert rows == [
        {"name": "OPTIONAL", "status": "OPTIONAL", "required_by": [], "optional_for": ["sample"]},
        {"name": "TOKEN", "status": "SET", "required_by": ["sample"], "optional_for": []},
    ]
    assert "super-secret" not in json.dumps(rows)
    metadata = json.loads((paths.state / "mcp-credentials.json").read_text(encoding="utf-8"))
    assert set(metadata) == {"version", "imported_at", "names"}
    assert metadata["version"] == 1
    assert metadata["names"] == ["TOKEN"]
    imported_at = datetime.fromisoformat(metadata["imported_at"])
    assert imported_at.utcoffset().total_seconds() == 0
    assert before <= imported_at <= after
    assert "super-secret" not in json.dumps(metadata)
    assert not any(isinstance(value, int) and value == len("super-secret") for value in metadata.values())


def test_import_metadata_names_are_sorted_and_omit_empty_values(tmp_path):
    store = credentials_module.McpCredentialStore(make_paths(tmp_path))
    source = tmp_path / "source.env"
    source.write_text("Z=z\nA=a\nEMPTY=\n", encoding="utf-8")
    store.import_file(source, [{"id": "server", "required_environment": ["Z", "EMPTY", "A"]}])
    metadata = json.loads(store.metadata_path.read_text(encoding="utf-8"))
    assert metadata["names"] == ["A", "Z"]


def test_import_rejects_unknown_names_before_changing_existing_vault(tmp_path):
    paths = make_paths(tmp_path)
    source = tmp_path / "source.env"
    store = credentials_module.McpCredentialStore(paths)
    source.write_text("TOKEN=original\n", encoding="utf-8")
    store.import_file(source, sample_servers())
    old_metadata = store.metadata_path.read_bytes()
    source.write_text("UNKNOWN=private-value\n", encoding="utf-8")
    with pytest.raises(AgentKitError) as raised:
        store.import_file(source, sample_servers())
    assert "private-value" not in str(raised.value)
    assert store.load() == {"TOKEN": "original"}
    assert store.metadata_path.read_bytes() == old_metadata


@pytest.mark.parametrize("failure", ["replace", "fsync"])
def test_import_failure_keeps_old_vault_and_cleans_temporary_files(tmp_path, monkeypatch, failure):
    paths = make_paths(tmp_path)
    store = credentials_module.McpCredentialStore(paths)
    source = tmp_path / "source.env"
    source.write_text("TOKEN=original\n", encoding="utf-8")
    store.import_file(source, sample_servers())
    old_metadata = store.metadata_path.read_bytes()
    source.write_text("TOKEN=private-new\n", encoding="utf-8")

    def fail(*args, **kwargs):
        raise OSError("private-new")

    monkeypatch.setattr(credentials_module.os, failure, fail)
    with pytest.raises(AgentKitError) as raised:
        store.import_file(source, sample_servers())
    assert "private-new" not in str(raised.value)
    assert store.load() == {"TOKEN": "original"}
    assert store.metadata_path.read_bytes() == old_metadata
    assert list(paths.secrets.iterdir()) == [store.vault_path]


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
@pytest.mark.parametrize("mode", [0o604, 0o640, 0o660, 0o601])
def test_load_rejects_insecure_permissions_without_echoing_values(tmp_path, mode):
    store = credentials_module.McpCredentialStore(make_paths(tmp_path))
    store.vault_path.parent.mkdir(parents=True)
    store.vault_path.write_text("TOKEN=private-value\n", encoding="utf-8")
    store.vault_path.chmod(mode)
    with pytest.raises(AgentKitError) as raised:
        store.load()
    assert "private-value" not in str(raised.value)


def test_load_and_status_treat_absent_or_empty_vault_values_as_missing(tmp_path):
    store = credentials_module.McpCredentialStore(make_paths(tmp_path))
    assert store.load() == {}
    assert {row["name"]: row["status"] for row in store.status(sample_servers())} == {
        "OPTIONAL": "OPTIONAL", "TOKEN": "MISSING",
    }
    source = tmp_path / "source.env"
    source.write_text("TOKEN=\nOPTIONAL=present\n", encoding="utf-8")
    store.import_file(source, sample_servers())
    assert {row["name"]: row["status"] for row in store.status(sample_servers())} == {
        "OPTIONAL": "SET", "TOKEN": "MISSING",
    }


def test_load_rejects_corrupt_vault_and_invalid_utf8_without_echoing_values(tmp_path):
    store = credentials_module.McpCredentialStore(make_paths(tmp_path))
    store.vault_path.parent.mkdir(parents=True)
    for content in (b"TOKEN=private-value\nTOKEN=other\n", b"TOKEN=private-value\xff\n"):
        store.vault_path.write_bytes(content)
        if os.name == "posix":
            store.vault_path.chmod(0o600)
        with pytest.raises(AgentKitError) as raised:
            store.load()
        assert "private-value" not in str(raised.value)


def test_import_read_errors_do_not_echo_values(tmp_path):
    store = credentials_module.McpCredentialStore(make_paths(tmp_path))
    source = tmp_path / "source.env"
    source.write_bytes(b"TOKEN=private-value\xff\n")
    with pytest.raises(AgentKitError) as raised:
        store.import_file(source, sample_servers())
    assert "private-value" not in str(raised.value)
    assert not store.vault_path.exists()


def test_clear_removes_only_the_canonical_vault_and_metadata(tmp_path):
    paths = make_paths(tmp_path)
    paths.secrets.mkdir(parents=True)
    paths.state.mkdir(parents=True)
    paths.secrets.joinpath("mcp-creds.env").write_text("TOKEN=value\n")
    paths.state.joinpath("mcp-credentials.json").write_text("{}")
    unrelated = paths.secrets / "unrelated.env"
    unrelated.write_text("keep\n")
    unrelated_state = paths.state / "unrelated.json"
    unrelated_state.write_text("{}")
    store = credentials_module.McpCredentialStore(paths)
    assert store.clear() is True
    assert not store.vault_path.exists()
    assert not store.metadata_path.exists()
    assert unrelated.read_text() == "keep\n"
    assert unrelated_state.read_text() == "{}"
    assert store.clear() is False


def test_ensure_runtime_creates_private_secrets_directory_and_preserves_positional_paths(tmp_path):
    data = tmp_path / "data"
    originals = [tmp_path / name for name in ("repository", "data", "runtime", "projects", "overrides", "installations", "state", "locks", "logs")]
    paths = KitPaths(*originals)
    assert paths.logs == tmp_path / "logs"
    assert paths.secrets == data / "secrets"
    ensure_runtime(paths)
    assert paths.secrets.is_dir()
    if os.name == "posix":
        paths.secrets.chmod(0o755)
        ensure_runtime(paths)
        assert stat.S_IMODE(paths.secrets.stat().st_mode) == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink; Windows reparse проверяется отдельной моделью")
@pytest.mark.parametrize("boundary,operation", [
    ("secrets", "import"), ("secrets", "load"), ("secrets", "clear"), ("secrets", "runtime"),
    ("vault", "import"), ("vault", "load"), ("vault", "clear"),
    ("state", "import"), ("state", "clear"),
])
def test_managed_credentials_reject_symlink_boundaries(tmp_path, operation, boundary):
    paths = make_paths(tmp_path)
    paths.data.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o755)
    external = outside / ("mcp-credentials.json" if boundary == "state" else "mcp-creds.env")
    external.write_text("TOKEN=outside-value\n")
    external.chmod(0o600)
    if boundary == "vault":
        paths.secrets.mkdir()
        (paths.secrets / "mcp-creds.env").symlink_to(external)
    else:
        getattr(paths, boundary).symlink_to(outside, target_is_directory=True)
    source = tmp_path / "source.env"
    source.write_text("TOKEN=new-value\n")
    store = credentials_module.McpCredentialStore(paths)
    with pytest.raises(AgentKitError):
        if operation == "import":
            store.import_file(source, sample_servers())
        elif operation == "load":
            store.load()
        elif operation == "clear":
            store.clear()
        else:
            ensure_runtime(paths)
    assert external.read_text() == "TOKEN=outside-value\n"
    assert stat.S_IMODE(outside.stat().st_mode) == 0o755
    assert sorted(path.name for path in outside.iterdir()) == [external.name]


@pytest.mark.parametrize("operation", ["import", "load", "clear", "runtime"])
def test_managed_credentials_reject_windows_reparse_directory(tmp_path, monkeypatch, operation):
    paths = make_paths(tmp_path)
    paths.secrets.mkdir(parents=True)
    source = tmp_path / "source.env"
    source.write_text("TOKEN=new-value\n")
    original_lstat = Path.lstat

    def reparse_lstat(path):
        observed = original_lstat(path)
        if path == paths.secrets:
            return SimpleNamespace(st_mode=observed.st_mode, st_file_attributes=0x400)
        return observed

    monkeypatch.setattr(Path, "lstat", reparse_lstat)
    store = credentials_module.McpCredentialStore(paths)
    with pytest.raises(AgentKitError):
        if operation == "import":
            store.import_file(source, sample_servers())
        elif operation == "runtime":
            ensure_runtime(paths)
        else:
            getattr(store, operation)()
    assert list(paths.secrets.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory descriptors")
def test_import_does_not_follow_directory_swap_before_chmod(tmp_path, monkeypatch):
    paths = make_paths(tmp_path)
    paths.secrets.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o755)
    moved = paths.data / "original-secrets"
    source = tmp_path / "source.env"
    source.write_text("TOKEN=new-value\n")
    original_fchmod = os.fchmod
    secrets_inode = paths.secrets.stat().st_ino

    def swap_directory(descriptor, mode):
        if os.fstat(descriptor).st_ino == secrets_inode and not moved.exists():
            paths.secrets.rename(moved)
            paths.secrets.symlink_to(outside, target_is_directory=True)
        original_fchmod(descriptor, mode)

    monkeypatch.setattr(os, "fchmod", swap_directory)
    credentials_module.McpCredentialStore(paths).import_file(source, sample_servers())
    assert paths.secrets.is_symlink()
    assert list(outside.iterdir()) == []
    assert stat.S_IMODE(outside.stat().st_mode) == 0o755
    assert (moved / "mcp-creds.env").read_text() == "TOKEN=new-value\n"


@pytest.mark.skipif(os.name != "posix", reason="Модель Windows file attributes поверх POSIX dir_fd")
@pytest.mark.parametrize("operation", ["import", "load", "clear"])
def test_managed_credentials_reject_windows_reparse_file(tmp_path, monkeypatch, operation):
    paths = make_paths(tmp_path)
    source = tmp_path / "source.env"
    source.write_text("TOKEN=original\n")
    store = credentials_module.McpCredentialStore(paths)
    store.import_file(source, sample_servers())
    original_stat = os.stat

    def reparse_stat(path, *args, **kwargs):
        observed = original_stat(path, *args, **kwargs)
        if path == "mcp-creds.env" and kwargs.get("dir_fd") is not None:
            return SimpleNamespace(st_mode=observed.st_mode, st_file_attributes=0x400)
        return observed

    monkeypatch.setattr(os, "stat", reparse_stat)
    with pytest.raises(AgentKitError):
        if operation == "import":
            store.import_file(source, sample_servers())
        else:
            getattr(store, operation)()
    assert store.vault_path.read_text() == "TOKEN=original\n"


@pytest.mark.parametrize("attributes,query_ok", [(0, True), (0x400, True), (0, False)])
def test_windows_boundary_checks_open_handle_reparse_tag_and_pins_object(tmp_path, monkeypatch, attributes, query_ok):
    import ctypes
    from ctypes import wintypes
    from agent_engineering_kit.managed_paths import _windows_pin

    opened, closed = [], []

    class WinFunction:
        def __init__(self, function):
            self.function = function

        def __call__(self, *args):
            return self.function(*args)

    def create(*args):
        opened.append(args)
        return 123

    def inspect(handle, kind, info, size):
        assert handle == 123 and kind == 9
        ctypes.cast(info, ctypes.POINTER(wintypes.DWORD))[0] = attributes
        return query_ok

    kernel = SimpleNamespace(CreateFileW=WinFunction(create), GetFileInformationByHandleEx=WinFunction(inspect), CloseHandle=WinFunction(closed.append))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    if attributes or not query_ok:
        with pytest.raises(AgentKitError):
            with _windows_pin(tmp_path):
                pytest.fail("Небезопасный handle разрешён")
    else:
        with _windows_pin(tmp_path):
            assert closed == []
    assert opened[0][1:3] == (0x80, 1)  # READ_ATTRIBUTES; только SHARE_READ.
    assert opened[0][4:6] == (3, 0x02200000)  # OPEN_EXISTING; OPEN_REPARSE_POINT.
    assert closed == [123]


class WindowsSecurityBoundary:
    """Модель файловой Win32-границы; orchestration остаётся настоящим."""

    def __init__(self, *, invalid_acl=False, fail_create=False):
        self.acls = {}
        self.handles = {}
        self.invalid_acl = invalid_acl
        self.fail_create = fail_create
        self.validation_contents = []

    def read_descriptor(self, path):
        return self.acls[path]

    def private_descriptor(self):
        return "owner-only"

    def protect(self, descriptor):
        return descriptor

    def create_file(self, path, descriptor):
        if self.fail_create:
            raise OSError("test Win32 failure")
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self.handles[handle] = path
        self.acls[path] = descriptor
        return handle

    def validate(self, handle, descriptor, *, preserve_owner):
        self.validation_contents.append(self.handles[handle].read_bytes())
        if self.invalid_acl:
            raise OSError("test Win32 ACL mismatch")
        if self.acls[self.handles[handle]] != descriptor:
            raise OSError("test Win32 ACL mismatch")

    def detach_fd(self, handle):
        return handle

    def close_handle(self, handle):
        os.close(handle)


@pytest.mark.parametrize("existing", [False, True])
def test_windows_acl_import_uses_private_descriptor_and_preserves_existing_restrictions(tmp_path, monkeypatch, existing):
    store = credentials_module.McpCredentialStore(make_paths(tmp_path))
    store.vault_path.parent.mkdir(parents=True)
    boundary = WindowsSecurityBoundary()
    if existing:
        store.vault_path.write_text("TOKEN=original\n", encoding="utf-8")
        boundary.acls[store.vault_path] = "explicit-owner-and-deny"
    expected = "explicit-owner-and-deny" if existing else "owner-only"
    source = tmp_path / "source.env"
    source.write_text("TOKEN=private-new\n", encoding="utf-8")
    real_replace = os.replace

    def replace(temporary, target):
        temporary = Path(temporary)
        assert boundary.acls[temporary] == (expected if target == store.vault_path else "owner-only")
        assert temporary.read_text(encoding="utf-8")
        real_replace(temporary, target)
        boundary.acls[target] = boundary.acls.pop(temporary)

    monkeypatch.setattr(credentials_module, "sys", SimpleNamespace(platform="win32"), raising=False)
    monkeypatch.setattr(credentials_module, "_WindowsSecurity", lambda: boundary, raising=False)
    monkeypatch.setattr(credentials_module.os, "replace", replace)
    store.import_file(source, sample_servers())
    assert boundary.acls[store.vault_path] == expected
    assert store.load() == {"TOKEN": "private-new"}


@pytest.mark.parametrize("failure", ["create", "validate"])
def test_windows_acl_import_fails_before_writing_secrets_when_security_is_unavailable(tmp_path, monkeypatch, failure):
    store = credentials_module.McpCredentialStore(make_paths(tmp_path))
    store.vault_path.parent.mkdir(parents=True)
    store.vault_path.write_text("TOKEN=original\n", encoding="utf-8")
    boundary = WindowsSecurityBoundary(invalid_acl=failure == "validate", fail_create=failure == "create")
    boundary.acls[store.vault_path] = "explicit-owner-and-deny"
    source = tmp_path / "source.env"
    source.write_text("TOKEN=private-new\n", encoding="utf-8")
    monkeypatch.setattr(credentials_module, "sys", SimpleNamespace(platform="win32"), raising=False)
    monkeypatch.setattr(credentials_module, "_WindowsSecurity", lambda: boundary, raising=False)
    with pytest.raises(AgentKitError) as raised:
        store.import_file(source, sample_servers())
    assert "private-new" not in str(raised.value)
    assert store.vault_path.read_text(encoding="utf-8") == "TOKEN=original\n"
    assert list(store.vault_path.parent.iterdir()) == [store.vault_path]
    for path in boundary.handles.values():
        assert not path.exists()
    assert boundary.validation_contents == ([b""] if failure == "validate" else [])


@pytest.mark.skipif(os.name != "nt", reason="Native Windows security descriptors")
@pytest.mark.parametrize("dacl", ["D:P(A;;FA;;;OW)", "D:P(D;;GR;;;BG)(A;;FA;;;OW)"])
def test_windows_acl_native_rotation_preserves_explicit_dacl(tmp_path, dacl):
    store = credentials_module.McpCredentialStore(make_paths(tmp_path))
    source = tmp_path / "source.env"
    source.write_text("TOKEN=original\n", encoding="utf-8")
    store.import_file(source, sample_servers())
    security = credentials_module._WindowsSecurity()
    ctypes = security.ctypes
    descriptor = ctypes.c_void_p()
    assert security.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(dacl, 1, ctypes.byref(descriptor), None)
    setter = security.advapi.SetFileSecurityW
    setter.argtypes = [security.types.LPCWSTR, security.types.DWORD, ctypes.c_void_p]
    setter.restype = security.types.BOOL
    try:
        assert setter(str(store.vault_path), 0x80000004, descriptor)
    finally:
        security.kernel.LocalFree(descriptor)
    original = security.read_descriptor(store.vault_path)
    source.write_text("TOKEN=private-new\n", encoding="utf-8")
    store.import_file(source, sample_servers())
    assert security.access_components(security.read_descriptor(store.vault_path)) == security.access_components(original)
    assert store.load() == {"TOKEN": "private-new"}
