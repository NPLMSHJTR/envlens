"""The rule engine: turn three sets of facts into a list of defensible findings.

The audit compares four sources of truth:

* what the code reads (``used``),
* what the example file promises (``declared``),
* what the developer's local file contains (``local``),
* what the deployment manifests actually supply (``provisioned``).

Every finding is a difference between two of those sets, and every finding names
the file and line that justify it. Rules that would require guessing are not
implemented; the closest thing is the *unprovisioned* rule, which refuses to run
at all when a manifest defers to a source that cannot be read statically.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path

from .dotenv import DotenvDoc, load_dotenv, looks_like_placeholder
from .manifests import ManifestScan, discover
from .model import Finding, Report, Severity
from .scanner import iter_files, scan_paths

DEFAULT_EXAMPLES = (".env.example", ".env.sample", ".env.template", ".env.dist", "example.env")
DEFAULT_LOCALS = (".env", ".env.local")
IGNORE_MARKER = "envlens:ignore"

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Stripe live secret key", re.compile(r"\bsk_live_[0-9A-Za-z]{8,}")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9]{32,}")),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
)


@dataclass(slots=True)
class Options:
    root: Path
    targets: list[str] = field(default_factory=lambda: ["."])
    example_files: list[str] = field(default_factory=list)
    local_files: list[str] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    ignore: list[str] = field(default_factory=list)
    manifests: bool = True
    fail_on: str = "error"


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def discover_examples(
    root: Path,
    targets: list[str],
    explicit: list[str],
    exclude: list[str],
) -> tuple[list[Path], list[str]]:
    """Return example files plus a list of explicitly requested paths that are missing."""
    if explicit:
        found: list[Path] = []
        missing: list[str] = []
        for item in explicit:
            candidate = (root / item).resolve()
            if candidate.is_file():
                found.append(candidate)
            else:
                missing.append(item)
        return found, missing

    matches: list[Path] = []
    for path in iter_files(root, targets, exclude):
        if path.name in DEFAULT_EXAMPLES:
            matches.append(path)
    matches.sort(key=lambda path: (len(path.relative_to(root).parts), _rel(root, path)))
    return matches, []


def discover_locals(root: Path, targets: list[str], explicit: list[str]) -> list[Path]:
    """Find developer env files: the repository root plus each audited directory."""
    if explicit:
        return [(root / item).resolve() for item in explicit if (root / item).is_file()]

    directories: list[Path] = [root]
    for target in targets:
        candidate = (root / target).resolve()
        if candidate.is_dir() and candidate != root:
            directories.append(candidate)

    found: list[Path] = []
    for directory in dict.fromkeys(directories):
        for name in DEFAULT_LOCALS:
            path = directory / name
            if path.is_file():
                found.append(path)
    return found


def _is_ignored(key: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(key, pattern) for pattern in patterns)


def _location(doc: DotenvDoc, root: Path, entry_line: int) -> tuple[str, int]:
    return _rel(root, doc.path), entry_line


def audit(options: Options) -> Report:
    """Run every rule and return a :class:`Report` sorted by severity."""
    root = options.root.resolve()
    report = Report(root=root.as_posix())

    examples, missing_examples = discover_examples(
        root, options.targets, options.example_files, options.exclude
    )
    locals_ = discover_locals(root, options.targets, options.local_files)
    for missing in missing_examples:
        report.notes.append(f"example file requested but not found: {missing}")

    example_docs = [load_dotenv(path) for path in examples]
    local_docs = [load_dotenv(path) for path in locals_]
    report.example_files = [_rel(root, path) for path in examples]
    report.local_files = [_rel(root, path) for path in locals_]

    used, coverage = scan_paths(root, options.targets, options.exclude, options.include)
    report.coverage = coverage
    report.used = used

    declared: dict[str, list[tuple[str, int]]] = {}
    inline_ignored: set[str] = set()
    for doc in example_docs:
        for entry in doc.kv_entries:
            assert entry.key is not None
            if IGNORE_MARKER in entry.raw:
                inline_ignored.add(entry.key)
                continue
            declared.setdefault(entry.key, []).append(_location(doc, root, entry.line))
    report.declared = declared

    local_keys: dict[str, list[tuple[str, int]]] = {}
    for doc in local_docs:
        for entry in doc.kv_entries:
            assert entry.key is not None
            local_keys.setdefault(entry.key, []).append(_location(doc, root, entry.line))

    manifest_scan = ManifestScan()
    if options.manifests:
        manifest_scan = discover(root, options.targets, options.exclude)
        report.manifest_files = manifest_scan.files
        report.provisioned = manifest_scan.keys

    ignored = set(inline_ignored)
    for key in list(declared) + list(used) + list(local_keys):
        if _is_ignored(key, options.ignore):
            ignored.add(key)

    findings: list[Finding] = []

    def add(
        rule: str,
        severity: Severity,
        key: str,
        message: str,
        file: str | None = None,
        line: int | None = None,
        hint: str | None = None,
    ) -> None:
        findings.append(Finding(rule, severity, key, message, file, line, hint))

    # Rule 1: a key the code reads that the contract never mentions.
    for key in sorted(set(used) - set(declared) - ignored):
        first = used[key][0]
        add(
            "missing-from-example",
            Severity.error,
            key,
            "read in code but not declared in any example file",
            first.file,
            first.line,
            "run `envlens fix` to append a placeholder, or add the key by hand",
        )

    # Rule 2: a key the contract promises that nothing reads.
    for key in sorted(set(declared) - set(used) - ignored):
        file, line = declared[key][0]
        add(
            "unused-in-code",
            Severity.warning,
            key,
            "declared in the example file but no scanned source reads it",
            file,
            line,
            "confirm it is not read by an unsupported language or an external image",
        )

    # Rules 3 and 4: drift between the contract and the developer's local file.
    if local_docs:
        for key in sorted(set(declared) - set(local_keys) - ignored):
            file, line = declared[key][0]
            add(
                "local-missing",
                Severity.warning,
                key,
                "declared in the example file but absent from the local env file",
                file,
                line,
                "copy the key into .env if the local build needs it",
            )
        for key in sorted(set(local_keys) - set(declared) - ignored):
            file, line = local_keys[key][0]
            add(
                "local-extra",
                Severity.warning,
                key,
                "present in the local env file but not declared in the example",
                file,
                line,
                "document the key in the example file so the next clone inherits it",
            )

    # Rule 5: a key the code reads that no runtime manifest supplies.
    if options.manifests and manifest_scan.runtime_files:
        if manifest_scan.unknown:
            report.notes.append(
                "provisioning check skipped: "
                + ", ".join(manifest_scan.unknown)
                + " cannot be resolved statically"
            )
        else:
            for key in sorted(set(used) - set(manifest_scan.keys) - ignored):
                first = used[key][0]
                add(
                    "unprovisioned",
                    Severity.error,
                    key,
                    "read in code but supplied by no runtime manifest",
                    first.file,
                    first.line,
                    "add it to docker-compose, the Kubernetes env list, or a Dockerfile ARG/ENV",
                )

    # Rule 6: real-looking credentials in a file that is meant to be committed.
    for doc in example_docs:
        for entry in doc.kv_entries:
            assert entry.key is not None and entry.value is not None
            if entry.key in ignored or looks_like_placeholder(entry.value):
                continue
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(entry.value):
                    file, line = _location(doc, root, entry.line)
                    add(
                        "secret-in-example",
                        Severity.error,
                        entry.key,
                        f"value looks like a real credential ({label})",
                        file,
                        line,
                        "rotate the credential, then replace the value with a placeholder",
                    )
                    break

    # Rule 7: duplicate declarations, where the last one silently wins.
    for doc in example_docs + local_docs:
        for key, entries in sorted(doc.duplicates().items()):
            for entry in entries[1:]:
                file, line = _location(doc, root, entry.line)
                add(
                    "duplicate-key",
                    Severity.warning,
                    key,
                    f"declared more than once (first at line {entries[0].line})",
                    file,
                    line,
                    "remove the extra declaration; loaders keep only one value",
                )

    # Rule 8: lines that are neither a comment, a blank line, nor an assignment.
    for doc in example_docs + local_docs:
        for entry in doc.invalid_entries():
            file, line = _location(doc, root, entry.line)
            add(
                "invalid-line",
                Severity.warning,
                "-",
                "line is not a comment or a KEY=VALUE assignment",
                file,
                line,
                "prefix the line with '#' if it is prose",
            )

    # Rule 9: two keys that differ only by case are one key in most shells.
    by_upper: dict[str, set[str]] = {}
    for key in set(declared) | set(local_keys):
        by_upper.setdefault(key.upper(), set()).add(key)
    for group in sorted(by_upper.values()):
        if len(group) > 1:
            for key in sorted(group):
                location = (declared.get(key) or local_keys.get(key) or [("", 0)])[0]
                add(
                    "case-collision",
                    Severity.warning,
                    key,
                    "keys differing only by case collide in POSIX shells",
                    location[0] or None,
                    location[1] or None,
                )

    report.findings = sorted(findings, key=Finding.sort_key)

    if not examples:
        report.notes.append(
            "no example file found; run `envlens init` to generate .env.example from the code"
        )
    if not options.manifests:
        report.notes.append("manifest analysis disabled; the unprovisioned rule did not run")
    if coverage.dynamic:
        report.notes.append(
            f"{len(coverage.dynamic)} dynamic access(es) could not be resolved statically"
        )

    return report
