"""A strict, dependency-free reader for dotenv files.

The parser is deliberately conservative: it recognises the syntax that the
major dotenv implementations agree on (``KEY=value``, ``export KEY=value``,
single and double quotes, ``#`` comments, BOM, CRLF) and records everything
else as an ``invalid`` entry instead of guessing. Multi-line double-quoted
values are supported because certificates and JSON blobs are common in real
files.

Values are returned unquoted but otherwise unmodified, so callers can inspect
them without re-implementing quoting rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "$": "$"}


@dataclass(slots=True)
class Entry:
    """One physical line of a dotenv file, classified."""

    key: str | None
    value: str | None
    line: int
    raw: str
    kind: str  # "kv" | "comment" | "blank" | "invalid"
    quote: str = ""


@dataclass(slots=True)
class DotenvDoc:
    """A parsed dotenv document that keeps every original line."""

    path: Path
    entries: list[Entry] = field(default_factory=list)

    @property
    def kv_entries(self) -> list[Entry]:
        return [entry for entry in self.entries if entry.kind == "kv"]

    @property
    def key_map(self) -> dict[str, list[Entry]]:
        mapping: dict[str, list[Entry]] = {}
        for entry in self.kv_entries:
            assert entry.key is not None
            mapping.setdefault(entry.key, []).append(entry)
        return mapping

    def keys(self) -> list[str]:
        return list(self.key_map)

    def duplicates(self) -> dict[str, list[Entry]]:
        return {key: entries for key, entries in self.key_map.items() if len(entries) > 1}

    def invalid_entries(self) -> list[Entry]:
        return [entry for entry in self.entries if entry.kind == "invalid"]


def _find_unescaped(text: str, char: str) -> int:
    index = 0
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == char:
            return index
        index += 1
    return -1


def _unescape_double(text: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            nxt = text[index + 1]
            out.append(_ESCAPES.get(nxt, "\\" + nxt))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _strip_inline_comment(value: str) -> str:
    """Drop a trailing ``# comment`` only when it is preceded by whitespace."""
    match = re.search(r"\s+#", value)
    if match is None:
        return value.strip()
    return value[: match.start()].strip()


def parse_dotenv(text: str, path: Path) -> DotenvDoc:
    """Parse ``text`` into a :class:`DotenvDoc` without touching the filesystem."""
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines()
    doc = DotenvDoc(path=path)
    index = 0
    total = len(lines)

    while index < total:
        raw = lines[index]
        line_no = index + 1
        stripped = raw.strip()

        if not stripped:
            doc.entries.append(Entry(None, None, line_no, raw, "blank"))
            index += 1
            continue
        if stripped.startswith("#"):
            doc.entries.append(Entry(None, None, line_no, raw, "comment"))
            index += 1
            continue

        body = stripped
        if body.startswith("export ") or body.startswith("export\t"):
            body = body[len("export") :].lstrip()

        key, separator, remainder = body.partition("=")
        key = key.strip()
        if not separator or not KEY_RE.match(key):
            doc.entries.append(Entry(None, None, line_no, raw, "invalid"))
            index += 1
            continue

        remainder = remainder.lstrip()
        quote = ""
        value = ""

        if remainder[:1] in ("'", '"'):
            quote = remainder[0]
            buffer = remainder[1:]
            if quote == '"':
                while True:
                    close_at = _find_unescaped(buffer, '"')
                    if close_at != -1:
                        value = _unescape_double(buffer[:close_at])
                        break
                    index += 1
                    if index >= total:
                        value = _unescape_double(buffer)
                        break
                    buffer = buffer + "\n" + lines[index]
            else:
                close_at = buffer.find("'")
                value = buffer if close_at == -1 else buffer[:close_at]
        else:
            value = _strip_inline_comment(remainder)

        doc.entries.append(Entry(key, value, line_no, raw, "kv", quote))
        index += 1

    return doc


def load_dotenv(path: Path) -> DotenvDoc:
    """Read and parse a dotenv file using UTF-8 with replacement on bad bytes."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_dotenv(text, path)


def looks_like_placeholder(value: str) -> bool:
    """Return ``True`` when a value is obviously a sample rather than a secret.

    The heuristic exists to keep secret detection from crying wolf on the
    ``changeme`` and ``your-key-here`` values that documentation is full of.
    It is intentionally allow-list based: unknown values are *not* assumed safe.
    """
    lowered = value.strip().lower()
    if not lowered:
        return True
    markers = ("example", "changeme", "change-me", "your", "<", "xxx", "dummy", "replace")
    if any(marker in lowered for marker in markers):
        return True
    return lowered in {"todo", "none", "null", "secret", "password", "token"}
