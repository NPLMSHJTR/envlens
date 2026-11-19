"""Static reference scanning for environment variables.

The scanner is regex based rather than AST based on purpose. A tree-sitter or
compiler-grade front end for a dozen languages would make the tool heavy to
install and slow to start, while the questions being answered ("which keys does
this file read?") are almost always answered by a single line of code. The price
of that choice is paid explicitly: anything the scanner cannot resolve is
counted as a dynamic access and reported, never silently dropped.

Every pattern carries a ``needle``. A line that does not contain any needle is
skipped before regex evaluation, which keeps large repositories fast.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .dotenv import KEY_RE
from .model import Coverage, Reference

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_LINE_CHARS = 4000
IGNORE_MARKER = "envlens:ignore"

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "node_modules",
    "dist",
    "build",
    "target",
    "vendor",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".output",
    "coverage",
    ".tox",
    ".nox",
    ".eggs",
    ".gradle",
    ".idea",
    ".vscode",
    "site-packages",
    "dist-packages",
}

# A virtual environment is identified by the marker file it contains, not by its
# directory name. Naming a venv ``.venv-check`` or ``env313`` must not cause the
# entire dependency tree to be scanned as project source.
VENV_MARKER = "pyvenv.cfg"

EXT_LANGUAGE = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".astro": "Astro",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".cs": "C#",
    ".swift": "Swift",
    ".dart": "Dart",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".scala": "Scala",
    ".sc": "Scala",
    ".c": "C/C++",
    ".h": "C/C++",
    ".cpp": "C/C++",
    ".cc": "C/C++",
    ".cxx": "C/C++",
    ".hpp": "C/C++",
    ".hh": "C/C++",
    ".lua": "Lua",
    ".r": "R",
    ".jl": "Julia",
    ".pl": "Perl",
    ".pm": "Perl",
    ".clj": "Clojure",
    ".cljs": "Clojure",
    ".cljc": "Clojure",
}

JS_LANGS = {"JavaScript", "TypeScript", "Vue", "Svelte", "Astro"}


@dataclass(frozen=True, slots=True)
class Pattern:
    language: str
    regex: re.Pattern[str]
    needles: tuple[str, ...]
    dynamic: bool = False


def _p(language: str, pattern: str, needles: tuple[str, ...], dynamic: bool = False) -> Pattern:
    return Pattern(language, re.compile(pattern), needles, dynamic)


PATTERNS: tuple[Pattern, ...] = (
    _p("Python", r"os\.environ\[\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*\]", ("environ",)),
    _p("Python", r"os\.environ\.get\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']", ("environ",)),
    _p("Python", r"os\.getenv\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']", ("getenv",)),
    _p("Python", r"os\.environ\.setdefault\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']", ("environ",)),
    _p(
        "JavaScript",
        r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)",
        ("process.env",),
    ),
    _p(
        "JavaScript",
        r"process\.env\[\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*\]",
        ("process.env",),
    ),
    _p("JavaScript", r"import\.meta\.env\.([A-Za-z_][A-Za-z0-9_]*)", ("import.meta.env",)),
    _p(
        "JavaScript",
        r"import\.meta\.env\[\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*\]",
        ("import.meta.env",),
    ),
    _p("Go", r"os\.Getenv\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"", ("os.Getenv",)),
    _p("Go", r"os\.LookupEnv\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"", ("os.LookupEnv",)),
    _p("Rust", r"env::var\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"", ("env::var",)),
    _p("Rust", r"env::var_os\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"", ("env::var_os",)),
    _p("Ruby", r"ENV\[\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*\]", ("ENV[",)),
    _p("Ruby", r"ENV\.fetch\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']", ("ENV.fetch",)),
    _p("PHP", r"getenv\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]", ("getenv",)),
    _p("PHP", r"\$_ENV\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]", ("_ENV",)),
    _p("Java", r"System\.getenv\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"", ("System.getenv",)),
    _p(
        "C#",
        r"Environment\.GetEnvironmentVariable\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"",
        ("GetEnvironmentVariable",),
    ),
    _p(
        "Swift",
        r"ProcessInfo\.processInfo\.environment\[\s*\"([A-Za-z_][A-Za-z0-9_]*)\"\s*\]",
        ("environment",),
    ),
    _p(
        "Dart",
        r"Platform\.environment\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]",
        ("Platform.environment",),
    ),
    _p(
        "Dart",
        r"String\.fromEnvironment\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]",
        ("fromEnvironment",),
    ),
    _p(
        "Elixir",
        r"System\.(?:get_env|fetch_env!?)\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"",
        ("System.",),
    ),
    _p("Scala", r"sys\.env\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"", ("sys.env",)),
    _p("Scala", r"sys\.env\.get\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"", ("sys.env",)),
    _p(
        "C/C++",
        r"(?:std::)?getenv\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"",
        ("getenv",),
    ),
    _p("Lua", r"os\.getenv\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]", ("os.getenv",)),
    _p("R", r"Sys\.getenv\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]", ("Sys.getenv",)),
    _p("Julia", r"ENV\[\s*\"([A-Za-z_][A-Za-z0-9_]*)\"\s*\]", ("ENV[",)),
    _p("Perl", r"\$ENV\{\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*\}", ("$ENV{",)),
    _p("Clojure", r"\(System/getenv\s+\"([A-Za-z_][A-Za-z0-9_]*)\"", ("System/getenv",)),
    _p("JavaScript", r"Deno\.env\.get\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']", ("Deno.env",)),
    _p("JavaScript", r"Bun\.env\.([A-Za-z_][A-Za-z0-9_]*)", ("Bun.env",)),
    # Dynamic forms: the key is not a literal, so it cannot be resolved statically.
    _p(
        "Python",
        r"os\.(?:environ\.get|getenv)\(\s*(?![\"'])([A-Za-z_][A-Za-z0-9_.]*)",
        ("getenv", "environ"),
        True,
    ),
    _p("Python", r"os\.environ\[\s*(?![\"'])([^\]]{1,60})\]", ("environ",), True),
    _p("JavaScript", r"process\.env\[\s*(?![\"'])([^\]]{1,60})\]", ("process.env",), True),
    _p("Go", r"os\.(?:Getenv|LookupEnv)\(\s*(?!\")", ("os.Getenv", "os.LookupEnv"), True),
    _p("Rust", r"env::var(?:_os)?\(\s*(?!\")", ("env::var",), True),
    _p("Ruby", r"ENV(?:\.fetch)?\[\s*(?![\"'])", ("ENV",), True),
    _p("Java", r"System\.getenv\(\s*(?!\")", ("System.getenv",), True),
    _p("Swift", r"ProcessInfo\.processInfo\.environment\[\s*(?!\")", ("environment",), True),
    _p("Dart", r"Platform\.environment\[\s*(?!['\"])", ("Platform.environment",), True),
    _p("Elixir", r"System\.(?:get_env|fetch_env!?)\(\s*(?!\")", ("System.",), True),
    _p("Scala", r"sys\.env(?:\.get)?\(\s*(?!\")", ("sys.env",), True),
    _p("C/C++", r"(?:std::)?getenv\(\s*(?!\")", ("getenv",), True),
    _p("Lua", r"os\.getenv\(\s*(?!['\"])", ("os.getenv",), True),
    _p("R", r"Sys\.getenv\(\s*(?!['\"])", ("Sys.getenv",), True),
    _p("Julia", r"ENV\[\s*(?!\")", ("ENV[",), True),
    _p("Clojure", r"\(System/getenv\s+(?!\")", ("System/getenv",), True),
)

_JS_DESTRUCTURE = re.compile(
    r"\{\s*([^{}]{1,400}?)\s*\}\s*=\s*(?:process\.env|import\.meta\.env)\b"
)
_JS_DESTRUCTURE_NEEDLES = ("process.env", "import.meta.env")


def language_for(path: Path) -> str | None:
    return EXT_LANGUAGE.get(path.suffix.lower())


def _js_destructured(line: str) -> list[str]:
    keys: list[str] = []
    for match in _JS_DESTRUCTURE.finditer(line):
        for chunk in match.group(1).split(","):
            candidate = chunk.split(":")[0].split("=")[0].strip()
            candidate = candidate.lstrip(".")
            if candidate and KEY_RE.match(candidate):
                keys.append(candidate)
    return keys


def scan_text(
    text: str, rel_path: str, language: str
) -> tuple[list[Reference], list[tuple[str, int, str]]]:
    """Scan one decoded file, returning literal references and dynamic accesses."""
    refs: list[Reference] = []
    dynamic: list[tuple[str, int, str]] = []
    patterns = [
        pattern
        for pattern in PATTERNS
        if pattern.language == language
        or (pattern.language == "JavaScript" and language in JS_LANGS)
    ]

    skip_next = False
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line[:MAX_LINE_CHARS]
        stripped = line.strip()
        if IGNORE_MARKER in line:
            # A marker on its own comment line silences the following line; an
            # inline trailing marker silences the line it sits on.
            skip_next = stripped.startswith(("#", "//", "/*", "*"))
            continue
        if skip_next:
            skip_next = False
            continue

        for pattern in patterns:
            if not any(needle in line for needle in pattern.needles):
                continue
            for match in pattern.regex.finditer(line):
                if pattern.dynamic:
                    dynamic.append((rel_path, number, language))
                    continue
                key = match.group(1) if match.groups() else ""
                if key and KEY_RE.match(key):
                    refs.append(Reference(key, rel_path, number, language))

        if language in JS_LANGS and any(needle in line for needle in _JS_DESTRUCTURE_NEEDLES):
            for key in _js_destructured(line):
                refs.append(Reference(key, rel_path, number, language))

    return refs, dynamic


def _matches_any(rel: str, name: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        normalized = pattern.replace("\\", "/").strip()
        if not normalized:
            continue
        if fnmatch.fnmatch(rel, normalized) or fnmatch.fnmatch(name, normalized):
            return True
        if normalized.endswith("/**") and rel.startswith(normalized[:-3].rstrip("/") + "/"):
            return True
        if rel.startswith(normalized.rstrip("/") + "/"):
            return True
    return False


def iter_files(
    root: Path,
    targets: list[str],
    exclude: list[str],
    *,
    force_explicit: bool = True,
) -> Iterator[Path]:
    """Yield candidate files under ``root``, pruning excluded and noisy dirs.

    Paths named explicitly on the command line outrank configuration excludes:
    ``envlens check services/api`` audits that directory even when the repository
    config excludes it from full-tree runs. Without this rule, a single exclude
    entry could make a targeted audit silently report nothing.
    """
    explicit = []
    if force_explicit:
        for target in targets:
            if target in (".", "./"):
                continue
            resolved = (root / target).resolve()
            if resolved.exists():
                explicit.append(resolved)

    def forced(path: Path) -> bool:
        return any(path == base or base in path.parents for base in explicit)

    for target in targets:
        candidate = (root / target).resolve()
        if candidate.is_file():
            yield candidate
            continue
        if not candidate.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(candidate, followlinks=False):
            kept: list[str] = []
            for name in sorted(dirnames):
                if name in SKIP_DIRS:
                    continue
                if (Path(dirpath) / name / VENV_MARKER).is_file():
                    continue
                kept.append(name)
            dirnames[:] = kept
            for filename in sorted(filenames):
                path = Path(dirpath) / filename
                try:
                    rel = path.relative_to(root).as_posix()
                except ValueError:
                    rel = path.name
                if exclude and not forced(path) and _matches_any(rel, filename, exclude):
                    continue
                yield path


def scan_paths(
    root: Path,
    targets: list[str],
    exclude: list[str],
    include: list[str] | None = None,
) -> tuple[dict[str, list[Reference]], Coverage]:
    """Scan ``targets`` (files or directories) and aggregate references by key."""
    coverage = Coverage()
    used: dict[str, list[Reference]] = {}
    seen: set[Path] = set()
    include = include or []
    # Resolve once: os.walk reports paths built from the resolved target, and on
    # Windows the resolved form can differ in case and 8.3 naming from what the
    # caller passed in.
    root = Path(root).resolve()

    for path in iter_files(root, targets, exclude):
        if path in seen:
            continue
        seen.add(path)
        language = language_for(path)
        if language is None:
            # Non-code files are not candidates, so they are not counted as skips.
            continue
        rel = path.relative_to(root).as_posix()
        if include and not _matches_any(rel, path.name, include):
            coverage.add_skip("not-included")
            continue
        try:
            data = path.read_bytes()
        except OSError:
            coverage.add_skip("unreadable")
            continue
        if len(data) > MAX_FILE_BYTES:
            coverage.add_skip("too-large")
            continue
        if b"\x00" in data[:8192]:
            coverage.add_skip("binary")
            continue

        text = data.decode("utf-8", errors="replace")
        refs, dynamic = scan_text(text, rel, language)
        coverage.files_scanned += 1
        coverage.add_language(language)
        for ref in refs:
            used.setdefault(ref.key, []).append(ref)
        for item in dynamic:
            coverage.add_dynamic(*item)

    return used, coverage
