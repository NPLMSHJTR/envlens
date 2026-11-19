"""Renderers for the three output formats.

Output is a product surface, so it is specified rather than incidental:

* ``text`` groups findings by rule, because a developer fixes one class of
  problem at a time.
* ``json`` is stable and versioned; every fact the text shows is present, plus
  coverage data that the text deliberately compresses.
* ``github`` emits workflow commands, so a failing check annotates the exact
  line in the pull request diff.

None of the renderers decide whether the run should fail. That belongs to
:func:`exit_code`, which keeps the threshold rule in one place.
"""

from __future__ import annotations

import json
import os
import sys
from typing import TextIO

from . import __version__
from .model import Finding, Report, Severity

RESET = "\033[0m"
STYLE = {
    "error": "\033[31m",
    "warning": "\033[33m",
    "info": "\033[36m",
    "dim": "\033[2m",
    "bold": "\033[1m",
}

FORMATS = ("text", "json", "github")


def use_color(mode: str, stream: TextIO | None = None) -> bool:
    """Decide whether to emit ANSI escapes."""
    if mode == "always":
        return True
    if mode == "never":
        return False
    if os.environ.get("NO_COLOR"):
        return False
    target = stream if stream is not None else sys.stdout
    return bool(getattr(target, "isatty", lambda: False)())


def _paint(text: str, style: str, enabled: bool) -> str:
    if not enabled or not style:
        return text
    return f"{STYLE.get(style, '')}{text}{RESET}"


def _shorten(items: list[str], limit: int = 3) -> str:
    if len(items) <= limit:
        return ", ".join(items)
    return ", ".join(items[:limit]) + f", +{len(items) - limit} more"


def _group(findings: list[Finding]) -> list[tuple[str, list[Finding]]]:
    groups: dict[str, list[Finding]] = {}
    for finding in findings:
        groups.setdefault(finding.rule, []).append(finding)
    return list(groups.items())


def render_text(report: Report, color: bool = False) -> str:
    """Human-readable report, grouped by rule."""
    lines: list[str] = []
    header = f"envlens {__version__}"
    lines.append(_paint(header, "bold", color) + "  " + _paint(report.root, "dim", color))

    context: list[str] = []
    if report.example_files:
        context.append("contract: " + _shorten(report.example_files))
    if report.local_files:
        context.append("local: " + _shorten(report.local_files))
    if report.manifest_files:
        context.append("manifests: " + _shorten(report.manifest_files))
    if context:
        lines.append(_paint(" · ".join(context), "dim", color))
    lines.append("")

    findings = report.sorted_findings()
    if not findings:
        lines.append(_paint("No findings.", "bold", color))
    else:
        width = min(max((len(finding.key) for finding in findings), default=8) + 2, 34)
        for rule, group in _group(findings):
            severity = group[0].severity.name
            label = _paint(f"{severity.upper():<7}", severity, color)
            description = group[0].message
            lines.append(f"{label} {rule} ({len(group)}) — {description}")
            for finding in group:
                location = ""
                if finding.file:
                    location = f"{finding.file}:{finding.line}" if finding.line else finding.file
                extra = ""
                if finding.message != description:
                    extra = " — " + finding.message
                lines.append(f"  {finding.key:<{width}} {_paint(location, 'dim', color)}{extra}")
            lines.append("")

    counts = report.counts()
    summary = (
        f"{counts['error']} error{'s' if counts['error'] != 1 else ''} · "
        f"{counts['warning']} warning{'s' if counts['warning'] != 1 else ''} · "
        f"{counts['info']} info"
    )
    lines.append(_paint(summary, "bold", color))

    coverage = report.coverage
    if coverage.files_scanned or coverage.skipped:
        ranked = sorted(coverage.languages.items(), key=lambda item: -item[1])
        languages = ", ".join(f"{name} {count}" for name, count in ranked)
        plural = "s" if coverage.files_scanned != 1 else ""
        detail = f"{coverage.files_scanned} file{plural} scanned"
        if languages:
            detail += f" ({languages})"
        if coverage.skipped:
            skipped = ", ".join(
                f"{count} {reason}" for reason, count in sorted(coverage.skipped.items())
            )
            detail += f" · skipped: {skipped}"
        if coverage.dynamic:
            detail += f" · {len(coverage.dynamic)} dynamic access(es) not verified"
        lines.append(_paint(detail, "dim", color))

    for note in report.notes:
        lines.append(_paint("note: " + note, "dim", color))

    return "\n".join(lines).rstrip() + "\n"


def _finding_payload(finding: Finding) -> dict[str, object]:
    return {
        "rule": finding.rule,
        "severity": finding.severity.name,
        "key": finding.key,
        "message": finding.message,
        "file": finding.file,
        "line": finding.line,
        "hint": finding.hint,
    }


def render_json(report: Report) -> str:
    """Machine-readable report. The schema is versioned by ``schema_version``."""
    payload = {
        "schema_version": 1,
        "tool": {"name": "envlens", "version": __version__},
        "root": report.root,
        "summary": {
            **report.counts(),
            "files_scanned": report.coverage.files_scanned,
            "dynamic_accesses": len(report.coverage.dynamic),
        },
        "findings": [_finding_payload(finding) for finding in report.sorted_findings()],
        "coverage": {
            "languages": dict(sorted(report.coverage.languages.items())),
            "skipped": dict(sorted(report.coverage.skipped.items())),
            "dynamic": [
                {"file": file, "line": line, "language": language}
                for file, line, language in report.coverage.dynamic
            ],
        },
        "files": {
            "example": report.example_files,
            "local": report.local_files,
            "manifests": report.manifest_files,
        },
        "notes": report.notes,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _escape_message(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text: str) -> str:
    return _escape_message(text).replace(":", "%3A").replace(",", "%2C")


def render_github(report: Report) -> str:
    """GitHub Actions workflow commands, one annotation per finding."""
    lines: list[str] = []
    for finding in report.sorted_findings():
        command = {"error": "error", "warning": "warning", "info": "notice"}[finding.severity.name]
        properties: list[str] = []
        if finding.file:
            properties.append("file=" + _escape_property(finding.file))
            if finding.line:
                properties.append(f"line={finding.line}")
        properties.append("title=" + _escape_property(f"envlens: {finding.rule}"))
        body = f"{finding.key} — {finding.message}"
        lines.append(f"::{command} {','.join(properties)}::{_escape_message(body)}")
    return "\n".join(lines) + ("\n" if lines else "")


def render(report: Report, fmt: str, color: bool = False) -> str:
    if fmt == "text":
        return render_text(report, color)
    if fmt == "json":
        return render_json(report)
    if fmt == "github":
        return render_github(report)
    raise ValueError(f"unknown format {fmt!r}")


def exit_code(report: Report, fail_on: str) -> int:
    """Map the report to a process exit code.

    ``never`` always succeeds, ``warning`` fails on warnings and errors, and
    ``error`` fails only on errors. Usage errors are handled by the CLI as 2.
    """
    if fail_on == "never":
        return 0
    threshold = Severity.error if fail_on == "error" else Severity.warning
    highest = report.highest_severity()
    if highest is None or highest < threshold:
        return 0
    return 1
