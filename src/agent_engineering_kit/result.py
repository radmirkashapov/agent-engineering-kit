"""Единый формат диагностических сообщений проверок."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    check: str
    message: str

    def render(self) -> str:
        return f"{self.severity:<7} [{self.check}] {self.message}"


@dataclass
class ValidationResult:
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def add(self, severity: str, check: str, message: str) -> None:
        self.diagnostics.append(Diagnostic(severity, check, message))

    def error(self, check: str, message: str) -> None:
        self.add("ERROR", check, message)

    def warning(self, check: str, message: str) -> None:
        self.add("WARNING", check, message)

    def info(self, check: str, message: str) -> None:
        self.add("INFO", check, message)

    def extend(self, other: "ValidationResult") -> None:
        self.diagnostics.extend(other.diagnostics)

    @property
    def ok(self) -> bool:
        return not any(item.severity == "ERROR" for item in self.diagnostics)
