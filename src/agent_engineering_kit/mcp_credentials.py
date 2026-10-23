"""Строгий разбор и machine-local хранилище credentials для MCP."""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from contextlib import ExitStack, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .errors import AgentKitError
from .paths import KitPaths
from .managed_paths import ManagedDirectory, managed_directory


class _WindowsSecurity:
    """Win32 security descriptors без внешних зависимостей."""

    # Owner, group, DACL и mandatory integrity label (без audit SACL).
    _INFORMATION = 0x17
    _PROTECTED = 0x1000

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.types = wintypes
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        pointer = ctypes.c_void_p
        signatures = {
            "GetFileSecurityW": ([wintypes.LPCWSTR, wintypes.DWORD, pointer, wintypes.DWORD, pointer], wintypes.BOOL),
            "GetSecurityInfo": ([wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, pointer, pointer, pointer, pointer, pointer], wintypes.DWORD),
            "ConvertStringSecurityDescriptorToSecurityDescriptorW": ([wintypes.LPCWSTR, wintypes.DWORD, pointer, pointer], wintypes.BOOL),
            "GetSecurityDescriptorLength": ([pointer], wintypes.DWORD),
            "IsValidSecurityDescriptor": ([pointer], wintypes.BOOL),
            "SetSecurityDescriptorControl": ([pointer, wintypes.WORD, wintypes.WORD], wintypes.BOOL),
            "GetSecurityDescriptorControl": ([pointer, pointer, pointer], wintypes.BOOL),
            "GetSecurityDescriptorDacl": ([pointer, pointer, pointer, pointer], wintypes.BOOL),
            "GetSecurityDescriptorSacl": ([pointer, pointer, pointer, pointer], wintypes.BOOL),
            "GetSecurityDescriptorOwner": ([pointer, pointer, pointer], wintypes.BOOL),
            "GetSecurityDescriptorGroup": ([pointer, pointer, pointer], wintypes.BOOL),
            "IsValidAcl": ([pointer], wintypes.BOOL),
            "IsValidSid": ([pointer], wintypes.BOOL),
            "GetLengthSid": ([pointer], wintypes.DWORD),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.advapi, name)
            function.argtypes, function.restype = arguments, result
        self.kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, pointer, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes, self.kernel.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
        self.kernel.LocalFree.argtypes, self.kernel.LocalFree.restype = [pointer], pointer

    @staticmethod
    def _require(result):
        if not result:
            raise OSError("Не удалось установить безопасный Windows ACL для credentials MCP")

    def read_descriptor(self, path: Path) -> bytes:
        size = self.types.DWORD()
        self.advapi.GetFileSecurityW(str(path), self._INFORMATION, None, 0, self.ctypes.byref(size))
        self._require(size.value and self.ctypes.get_last_error() == 122)
        descriptor = self.ctypes.create_string_buffer(size.value)
        self._require(self.advapi.GetFileSecurityW(str(path), self._INFORMATION, descriptor, size, self.ctypes.byref(size)))
        return descriptor.raw

    def private_descriptor(self) -> bytes:
        descriptor = self.ctypes.c_void_p()
        self._require(self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            "D:P(A;;FA;;;OW)", 1, self.ctypes.byref(descriptor), None,
        ))
        try:
            return self.ctypes.string_at(descriptor, self.advapi.GetSecurityDescriptorLength(descriptor))
        finally:
            self.kernel.LocalFree(descriptor)

    def protect(self, descriptor: bytes) -> bytes:
        buffer = self.ctypes.create_string_buffer(descriptor, len(descriptor))
        self._require(self.advapi.IsValidSecurityDescriptor(buffer))
        self._require(self.advapi.SetSecurityDescriptorControl(buffer, self._PROTECTED, self._PROTECTED))
        self.access_components(buffer.raw)
        return buffer.raw

    def create_file(self, path: Path, descriptor: bytes):
        ctypes, wintypes = self.ctypes, self.types

        class SecurityAttributes(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wintypes.BOOL)]

        buffer = ctypes.create_string_buffer(descriptor, len(descriptor))
        attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), ctypes.cast(buffer, ctypes.c_void_p), False)
        # CREATE_NEW, без sharing и без наследования handle. ACL задан до создания.
        handle = self.kernel.CreateFileW(str(path), 0x40020000, 0, ctypes.byref(attributes), 1, 0x80, None)
        self._require(handle != ctypes.c_void_p(-1).value)
        return handle

    def access_components(self, descriptor: bytes) -> tuple:
        ctypes, wintypes = self.ctypes, self.types
        buffer = ctypes.create_string_buffer(descriptor, len(descriptor))
        self._require(self.advapi.IsValidSecurityDescriptor(buffer))
        components = []
        for name in ("Owner", "Group"):
            sid, defaulted = ctypes.c_void_p(), wintypes.BOOL()
            self._require(getattr(self.advapi, f"GetSecurityDescriptor{name}")(buffer, ctypes.byref(sid), ctypes.byref(defaulted)))
            if sid:
                self._require(self.advapi.IsValidSid(sid))
            components.append(ctypes.string_at(sid, self.advapi.GetLengthSid(sid)) if sid else b"")
        for name in ("Dacl", "Sacl"):
            present, defaulted, acl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
            self._require(getattr(self.advapi, f"GetSecurityDescriptor{name}")(
                buffer, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted),
            ))
            if name == "Dacl":
                self._require(present.value and acl.value)
            if acl:
                self._require(self.advapi.IsValidAcl(acl))
                size = int.from_bytes(ctypes.string_at(acl, 4)[2:4], "little")
                components.append(ctypes.string_at(acl, size))
            else:
                components.append(b"")
        control, revision = wintypes.WORD(), wintypes.DWORD()
        self._require(self.advapi.GetSecurityDescriptorControl(buffer, ctypes.byref(control), ctypes.byref(revision)))
        components.append(bool(control.value & self._PROTECTED))
        return tuple(components)

    def validate(self, handle, descriptor: bytes, *, preserve_owner: bool) -> None:
        actual = self.ctypes.c_void_p()
        result = self.advapi.GetSecurityInfo(handle, 1, self._INFORMATION, None, None, None, None, self.ctypes.byref(actual))
        self._require(result == 0)
        try:
            observed = self.access_components(self.ctypes.string_at(actual, self.advapi.GetSecurityDescriptorLength(actual)))
        finally:
            self.kernel.LocalFree(actual)
        expected = self.access_components(descriptor)
        self._require(observed[2] == expected[2] and observed[4])
        if preserve_owner:
            self._require(observed == expected)

    @staticmethod
    def detach_fd(handle) -> int:
        import msvcrt

        return msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY | os.O_NOINHERIT)

    def close_handle(self, handle) -> None:
        self.kernel.CloseHandle(handle)


def _windows_private_temporary(path: Path) -> tuple[int, Path]:
    security = _WindowsSecurity()
    existing = path.exists()
    descriptor = security.protect(security.read_descriptor(path) if existing else security.private_descriptor())
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}"
    handle = security.create_file(temporary, descriptor)
    try:
        security.validate(handle, descriptor, preserve_owner=existing)
        return security.detach_fd(handle), temporary
    except BaseException:
        security.close_handle(handle)
        temporary.unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class CredentialRequirement:
    name: str
    required_by: tuple[str, ...]
    optional_for: tuple[str, ...]


def credential_requirements(servers: Iterable[dict[str, Any]]) -> dict[str, CredentialRequirement]:
    owners: dict[str, dict[str, set[str]]] = {}
    for server in servers:
        identifier = str(server["id"])
        required = {str(name) for name in server.get("required_environment", [])}
        referenced = {
            str(value)[4:]
            for value in server.get("environment", {}).values()
            if str(value).startswith("env:")
        } | required
        for name in referenced:
            bucket = owners.setdefault(name, {"required": set(), "optional": set()})
            bucket["required" if name in required else "optional"].add(identifier)
    return {
        name: CredentialRequirement(
            name=name,
            required_by=tuple(sorted(bucket["required"])),
            optional_for=tuple(sorted(bucket["optional"])),
        )
        for name, bucket in sorted(owners.items())
    }


def parse_credentials(text: str, *, allowed: set[str] | None) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, line in enumerate(text.split("\n"), start=1):
        line = line.removesuffix("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
            raise AgentKitError(f"Строка {number}: некорректное присваивание credentials")
        if name in values:
            raise AgentKitError(f"Строка {number}: повторная переменная {name}")
        if allowed is not None and name not in allowed:
            raise AgentKitError(f"Строка {number}: неизвестная переменная {name}")
        if any(marker in value for marker in ("`", "$(", "${", "\x00", "\r")):
            raise AgentKitError(f"Строка {number}: небезопасный синтаксис переменной {name}")
        values[name] = value
    return values


class McpCredentialStore:
    def __init__(self, paths: KitPaths):
        self.paths = paths

    @property
    def vault_path(self) -> Path:
        return self.paths.secrets / "mcp-creds.env"

    @property
    def metadata_path(self) -> Path:
        return self.paths.state / "mcp-credentials.json"

    def import_file(self, source: Path, servers: Iterable[dict[str, Any]]) -> Path:
        requirements = credential_requirements(servers)
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise AgentKitError("Не удалось прочитать файл credentials MCP") from None
        values = parse_credentials(text, allowed=set(requirements))
        # Проверить обе границы до первого изменения vault.
        try:
            for path in (self.vault_path, self.metadata_path):
                with managed_directory(self.paths.data, path.parent) as directory:
                    if directory is not None:
                        directory.file_info(path.name)
        except OSError:
            raise AgentKitError("Не удалось проверить границы хранилища credentials MCP") from None
        self._write_private(values)
        self._write_metadata(names=sorted(name for name, value in values.items() if value))
        return self.vault_path

    def load(self) -> dict[str, str]:
        try:
            with managed_directory(self.paths.data, self.paths.secrets) as directory:
                if directory is None:
                    return {}
                with directory.read(self.vault_path.name) as stream:
                    if stream is None:
                        return {}
                    text = stream.read()
        except (OSError, UnicodeError):
            raise AgentKitError("Не удалось прочитать хранилище credentials MCP") from None
        return parse_credentials(text, allowed=None)

    def status(self, servers: Iterable[dict[str, Any]]) -> list[dict[str, object]]:
        requirements = credential_requirements(servers)
        values = self.load()
        return [
            {
                "name": name,
                "status": "SET" if values.get(name) else ("MISSING" if requirement.required_by else "OPTIONAL"),
                "required_by": list(requirement.required_by),
                "optional_for": list(requirement.optional_for),
            }
            for name, requirement in requirements.items()
        ]

    def clear(self) -> bool:
        try:
            with ExitStack() as stack:
                targets = [(stack.enter_context(managed_directory(self.paths.data, path.parent)), path.name)
                           for path in (self.vault_path, self.metadata_path)]
                # Полный preflight до удаления любого из двух файлов.
                for directory, name in targets:
                    if directory is not None:
                        directory.file_info(name)
                existed = False
                for directory, name in targets:
                    if directory is not None:
                        existed = directory.unlink(name) or existed
        except OSError:
            raise AgentKitError("Не удалось удалить хранилище credentials MCP") from None
        return existed

    def _write_private(self, values: dict[str, str]) -> None:
        try:
            with managed_directory(self.paths.data, self.paths.secrets, create=True, private=True) as directory:
                self._atomic_write(self.vault_path, "".join(f"{name}={value}\n" for name, value in sorted(values.items())), directory)
        except (OSError, UnicodeError):
            raise AgentKitError("Не удалось сохранить хранилище credentials MCP") from None

    def _write_metadata(self, *, names: list[str]) -> None:
        metadata = {
            "version": 1,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "names": names,
        }
        try:
            with managed_directory(self.paths.data, self.metadata_path.parent, create=True) as directory:
                self._atomic_write(self.metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", directory)
        except (OSError, UnicodeError):
            raise AgentKitError("Не удалось сохранить метаданные credentials MCP") from None

    @staticmethod
    def _atomic_write(path: Path, content: str, directory: ManagedDirectory) -> None:
        path = directory.path / path.name
        directory.file_info(path.name)
        if sys.platform == "win32":
            # Удерживаем существующий файл до копирования ACL и создания temp.
            from .managed_paths import _windows_pin
            with (_windows_pin(path) if os.name == "nt" and path.exists() else nullcontext()):
                descriptor, temporary = _windows_private_temporary(path)
        else:
            temporary = f".{path.name}.{uuid.uuid4().hex}"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory.descriptor)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                if sys.platform != "win32" and os.name == "posix":
                    os.fchmod(stream.fileno(), 0o600)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            directory.file_info(path.name)
            if sys.platform == "win32":
                os.replace(temporary, path)
            else:
                os.replace(temporary, path.name, src_dir_fd=directory.descriptor, dst_dir_fd=directory.descriptor)
        finally:
            try:
                if sys.platform == "win32":
                    os.unlink(temporary)
                else:
                    os.unlink(temporary, dir_fd=directory.descriptor)
            except FileNotFoundError:
                pass
