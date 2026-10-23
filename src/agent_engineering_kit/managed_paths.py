"""Границы machine-local файлов: без symlink и Windows reparse points."""

from __future__ import annotations

import os
import stat
import sys
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from .errors import AgentKitError


def _reject_link(info) -> None:
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise AgentKitError("Небезопасная ссылка в managed-хранилище MCP")


@contextmanager
def _windows_pin(path: Path):
    """Handle без WRITE/DELETE sharing удерживает объект и запрещает его подмену."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    # FILE_READ_ATTRIBUTES, SHARE_READ, OPEN_EXISTING, OPEN_REPARSE_POINT | BACKUP_SEMANTICS.
    handle = kernel.CreateFileW(str(path), 0x80, 1, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError("Не удалось удержать managed-путь MCP")
    try:
        class AttributeTag(ctypes.Structure):
            _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

        tag = AttributeTag()
        if not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(tag), ctypes.sizeof(tag)) or tag.attributes & 0x400:
            raise AgentKitError("Небезопасный reparse point в managed-хранилище MCP")
        yield
    finally:
        kernel.CloseHandle(handle)


@dataclass
class ManagedDirectory:
    path: Path
    descriptor: int | None

    def file_info(self, name: str):
        try:
            info = (os.stat(name, dir_fd=self.descriptor, follow_symlinks=False)
                    if self.descriptor is not None else (self.path / name).lstat())
        except FileNotFoundError:
            return None
        _reject_link(info)
        if not stat.S_ISREG(info.st_mode):
            raise AgentKitError("Ожидался обычный файл managed-хранилища MCP")
        return info

    @contextmanager
    def read(self, name: str):
        with ExitStack() as stack:
            if self.file_info(name) is None:
                yield None
                return
            if self.descriptor is None:
                stack.enter_context(_windows_pin(self.path / name))
                descriptor = os.open(self.path / name, os.O_RDONLY | os.O_BINARY)
            else:
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.descriptor)
            stream = stack.enter_context(os.fdopen(descriptor, "r", encoding="utf-8"))
            info = os.fstat(stream.fileno())
            _reject_link(info)
            if not stat.S_ISREG(info.st_mode):
                raise AgentKitError("Ожидался обычный файл managed-хранилища MCP")
            if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
                raise AgentKitError("Небезопасные права хранилища credentials MCP: требуется 0600")
            yield stream

    def unlink(self, name: str) -> bool:
        if self.file_info(name) is None:
            return False
        if self.descriptor is None:
            (self.path / name).unlink()
        else:
            os.unlink(name, dir_fd=self.descriptor)
        return True


@contextmanager
def managed_directory(root: Path, directory: Path, *, create: bool = False, private: bool = False):
    """Открыть потомка canonical data root, удерживая каждый компонент пути.

    POSIX операции используют dir_fd/O_NOFOLLOW; Windows удерживает directory
    handles без sharing на запись/удаление и проверяет reparse tag на handle.
    Отсутствующий каталог при чтении не создаётся.
    """
    try:
        relative = directory.absolute().relative_to(root.absolute())
    except ValueError:
        raise AgentKitError("Managed-хранилище MCP находится за пределами data home") from None
    if not relative.parts or ".." in relative.parts:
        raise AgentKitError("Некорректный путь managed-хранилища MCP")
    canonical_root = root.resolve()
    with ExitStack() as stack:
        if create:
            canonical_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        elif not canonical_root.exists():
            yield None
            return
        descriptor = None
        current = canonical_root
        if sys.platform == "win32":
            stack.enter_context(_windows_pin(current))
        else:
            descriptor = os.open(current, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, descriptor)
        for part in relative.parts:
            current = current / part
            try:
                _reject_link(current.lstat())
            except FileNotFoundError:
                if not create:
                    yield None
                    return
                try:
                    if descriptor is None:
                        current.mkdir(mode=0o700)
                    else:
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass  # Конкурентное создание всё равно проходит no-follow open ниже.
                _reject_link(current.lstat())
            if descriptor is None:
                stack.enter_context(_windows_pin(current))
            else:
                descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                stack.callback(os.close, descriptor)
        if private and os.name == "posix":
            os.fchmod(descriptor, 0o700)
        yield ManagedDirectory(current, descriptor)
