"""Core data types shared by the scanner, the rule engine, and the renderers.

The model is intentionally small. A :class:`Finding` is a single statement about
one environment variable, and every statement carries the rule that produced it
plus the source location that justifies it. Renderers never invent information;
they only format what the audit layer has already proven.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Severity(IntEnum):
    """Ordered severity. Larger integers sort first in reports."""

    info = 10
    warning = 20
    error = 30

    @classmethod
    def parse(cls, name: str) -> Severity:
        """Parse a user-supplied severity name, raising ``ValueError`` if invalid."""
        try:
            return cls[name.strip().lower()]
        except KeyError as exc:
            valid = ", ".join(s.name for s in (cls.info, cls.warning, cls.error))
            raise ValueError(f"unknown severity {name!r}; expected one of: {valid}") from exc


@dataclass(frozen=True, slots=True)
class Finding:
    """One audit statement about one variable.

    ``file`` is a POSIX-style path relative to the audit root, or ``None`` when
    the finding is about the repository as a whole. ``line`` is 1-based.
    """

    rule: str
    severity: Severity
    key: str
    message: str
    file: str | None = None
    line: int | None = None
    hint: str | None = None

    def sort_key(self) -> tuple[int, str, str, int, str]:
        return (-int(self.severity), self.rule, self.file or "", self.line or 0, self.key)


@dataclass(slots=True)
class Coverage:
    """What the scan actually looked at, and what it could not resolve.

    Publishing coverage is a deliberate design choice: a static tool that hides
    its blind spots invites false confidence. Every skip is counted and every
    dynamic access is recorded.
    """

    files_scanned: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    dynamic: list[tuple[str, int, str]] = field(default_factory=list)

    def add_language(self, language: str) -> None:
        self.languages[language] = self.languages.get(language, 0) + 1

    def add_skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def add_dynamic(self, file: str, line: int, language: str) -> None:
        self.dynamic.append((file, line, language))


@dataclass(frozen=True, slots=True)
class Reference:
    """A place in the source tree that reads an environment variable."""

    key: str
    file: str
    line: int
    language: str

    @property
    def location(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass(slots=True)
class Report:
    """The complete result of one audit run."""

    root: str
    findings: list[Finding] = field(default_factory=list)
    coverage: Coverage = field(default_factory=Coverage)
    example_files: list[str] = field(default_factory=list)
    local_files: list[str] = field(default_factory=list)
    manifest_files: list[str] = field(default_factory=list)
    declared: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    used: dict[str, list[Reference]] = field(default_factory=dict)
    provisioned: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        result = {"error": 0, "warning": 0, "info": 0}
        for finding in self.findings:
            result[finding.severity.name] += 1
        return result

    def sorted_findings(self) -> list[Finding]:
        return sorted(self.findings, key=Finding.sort_key)

    def highest_severity(self) -> Severity | None:
        if not self.findings:
            return None
        return max(finding.severity for finding in self.findings)

    def keys_read_in_code(self) -> set[str]:
        return set(self.used)

    def keys_declared(self) -> set[str]:
        return set(self.declared)
