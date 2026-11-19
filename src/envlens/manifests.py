"""Provisioning manifests: where a variable is actually supplied at runtime.

A key can be read by code and documented in ``.env.example`` and still be
missing in production, because the thing that runs the container never learned
about it. This module extracts the keys that deployment and CI manifests supply:
Docker Compose, Kubernetes workloads, Dockerfiles, and GitHub Actions.

Two design rules keep the output trustworthy:

1. Only explicit, unambiguous syntax is counted. A YAML ``environment:`` block is
   read line by line with indentation tracking; structural keys such as
   ``valueFrom`` are excluded by name.
2. When a manifest defers to something this tool cannot read — an ``env_file``
   that does not exist locally, or Kubernetes ``envFrom`` — the manifest is
   marked *unknown* instead of *empty*. Callers must not conclude that a key is
   unprovisioned on the strength of an unknown manifest.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .dotenv import load_dotenv
from .scanner import iter_files

COMPOSE_NAME = re.compile(r"^(?:docker-)?compose(?:\.[\w-]+)*\.ya?ml$", re.IGNORECASE)
DOCKERFILE_NAME = re.compile(r"^(?:Dockerfile(?:\.[\w-]+)?|[\w-]+\.Dockerfile)$")
FLY_NAME = "fly.toml"
NETLIFY_NAME = "netlify.toml"
RENDER_NAMES = {"render.yaml", "render.yml"}
HEROKU_NAME = "app.json"
K8S_KIND = re.compile(r"^kind:\s*(\w+)", re.MULTILINE)

SECTION = re.compile(r"^(\s*)(environment|env)\s*:\s*$")
ENV_FROM = re.compile(r"^\s*envFrom\s*:")
ENV_FILE = re.compile(r"^(\s*)env_file\s*:\s*(.*)$")
LIST_NAME = re.compile(r"^\s*-\s*name\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*$")
LIST_ASSIGN = re.compile(r"^\s*-\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
LIST_BARE = re.compile(r"^\s*-\s*([A-Za-z_][A-Za-z0-9_]*)\s*$")
MAP_ITEM = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")
RENDER_SECTION = re.compile(r"^(\s*)envVars\s*:\s*$")
RENDER_KEY = re.compile(r"^\s*-\s*key\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*$")
INTERPOLATION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?[-?+][^}]*)?\}")
GHA_REFERENCE = re.compile(r"\$\{\{\s*(?:secrets|vars)\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
DOCKERFILE_ARG = re.compile(r"^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
DOCKERFILE_ENV = re.compile(r"^\s*ENV\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)

# YAML keys that live inside env blocks but are not environment variables.
STRUCTURAL = {
    "value",
    "valuefrom",
    "name",
    "key",
    "optional",
    "configmapkeyref",
    "secretkeyref",
    "fieldref",
    "envfrom",
    "prefix",
}


@dataclass(slots=True)
class ManifestScan:
    """Aggregated view of every provisioning source found in a repository.

    ``keys`` holds runtime provisioning only (Compose, Kubernetes, Dockerfile).
    ``ci_keys`` is kept separate because a secret referenced by a workflow is
    evidence that CI knows the value, not proof that the deployed container
    receives it.
    """

    files: list[str] = field(default_factory=list)
    runtime_files: list[str] = field(default_factory=list)
    keys: dict[str, list[str]] = field(default_factory=dict)
    ci_keys: dict[str, list[str]] = field(default_factory=dict)
    unknown: list[str] = field(default_factory=list)

    def add(self, key: str, source: str, ci: bool = False) -> None:
        bucket = (self.ci_keys if ci else self.keys).setdefault(key, [])
        if source not in bucket:
            bucket.append(source)

    def mark_unknown(self, source: str, reason: str) -> None:
        entry = f"{source} ({reason})"
        if entry not in self.unknown:
            self.unknown.append(entry)


def extract_env_sections(text: str) -> tuple[set[str], bool]:
    """Extract keys from ``environment:`` / ``env:`` blocks.

    Handles the three shapes that appear in the wild: Compose map values,
    Compose list values (``- KEY=value`` or bare ``- KEY``), and Kubernetes
    container env lists (``- name: KEY``).
    """
    keys: set[str] = set()
    unknown = False
    active_indent: int | None = None

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))

        if ENV_FROM.match(raw):
            unknown = True

        if active_indent is not None and indent <= active_indent:
            active_indent = None

        section = SECTION.match(raw)
        if section:
            active_indent = len(section.group(1))
            continue
        if active_indent is None:
            continue

        for pattern in (LIST_NAME, LIST_ASSIGN, LIST_BARE):
            match = pattern.match(raw)
            if match:
                keys.add(match.group(1))
                break
        else:
            match = MAP_ITEM.match(raw)
            if match and match.group(1).lower() not in STRUCTURAL:
                keys.add(match.group(1))

    return keys, unknown


def _env_file_paths(text: str) -> list[str]:
    """Return the ``env_file`` targets declared in a Compose file."""
    paths: list[str] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        match = ENV_FILE.match(raw)
        if not match:
            index += 1
            continue
        indent = len(match.group(1))
        inline = match.group(2).strip().strip("\"'")
        if inline and inline not in {"|", ">", "|-", ">-"}:
            paths.append(inline)
            index += 1
            continue
        index += 1
        while index < len(lines):
            child = lines[index]
            if not child.strip() or child.lstrip().startswith("#"):
                index += 1
                continue
            child_indent = len(child) - len(child.lstrip(" "))
            if child_indent <= indent:
                break
            item = child.strip().lstrip("-").strip().strip("\"'")
            if item:
                paths.append(item)
            index += 1
    return paths


def _render_keys(text: str) -> set[str]:
    """Extract ``- key: NAME`` entries from Render's ``envVars`` block."""
    keys: set[str] = set()
    active_indent: int | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if active_indent is not None and indent <= active_indent:
            active_indent = None
        section = RENDER_SECTION.match(raw)
        if section:
            active_indent = len(section.group(1))
            continue
        if active_indent is None:
            continue
        match = RENDER_KEY.match(raw)
        if match:
            keys.add(match.group(1))
    return keys


def parse_manifest(text: str, rel: str, kind: str, base: Path) -> ManifestScan:
    """Parse a single manifest file into a :class:`ManifestScan`."""
    scan = ManifestScan()
    scan.files.append(rel)

    if kind == "dockerfile":
        scan.runtime_files.append(rel)
        for match in DOCKERFILE_ARG.finditer(text):
            scan.add(match.group(1), rel)
        for match in DOCKERFILE_ENV.finditer(text):
            scan.add(match.group(1), rel)
        return scan

    if kind in ("fly", "netlify"):
        scan.runtime_files.append(rel)
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            scan.mark_unknown(rel, "cannot parse TOML")
            return scan
        if kind == "fly":
            env = data.get("env")
            if isinstance(env, dict):
                for key in env:
                    scan.add(key, rel)
            return scan

        build = data.get("build")
        if isinstance(build, dict) and isinstance(build.get("environment"), dict):
            for key in build["environment"]:
                scan.add(key, rel)
        context = data.get("context")
        if isinstance(context, dict):
            for value in context.values():
                if isinstance(value, dict) and isinstance(value.get("environment"), dict):
                    for key in value["environment"]:
                        scan.add(key, rel)
        return scan

    if kind == "heroku":
        scan.runtime_files.append(rel)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            scan.mark_unknown(rel, "cannot parse JSON")
            return scan
        env = data.get("env") if isinstance(data, dict) else None
        if isinstance(env, dict):
            for key in env:
                scan.add(key, rel)
        return scan

    if kind == "render":
        scan.runtime_files.append(rel)
        for key in _render_keys(text):
            scan.add(key, rel)
        return scan

    keys, unknown = extract_env_sections(text)
    if kind == "ci":
        for key in keys:
            scan.add(key, rel, ci=True)
    else:
        for key in keys:
            scan.add(key, rel)
    if unknown and kind != "ci":
        scan.mark_unknown(rel, "envFrom")

    if kind == "compose":
        scan.runtime_files.append(rel)
        for match in INTERPOLATION.finditer(text):
            scan.add(match.group(1), rel)
        for relative in _env_file_paths(text):
            candidate = (base / relative).resolve()
            try:
                candidate.relative_to(base.resolve())
            except ValueError:
                scan.mark_unknown(rel, f"env_file outside repository: {relative}")
                continue
            if candidate.is_file():
                doc = load_dotenv(candidate)
                for key in doc.key_map:
                    scan.add(key, rel)
            else:
                scan.mark_unknown(rel, f"env_file not found: {relative}")
    elif kind == "k8s":
        scan.runtime_files.append(rel)
    elif kind == "ci":
        for match in GHA_REFERENCE.finditer(text):
            scan.add(match.group(1), rel, ci=True)

    return scan


def discover(root: Path, targets: list[str], exclude: list[str]) -> ManifestScan:
    """Walk ``targets`` under ``root`` and aggregate every recognised manifest."""
    total = ManifestScan()
    for path in iter_files(root, targets, exclude):
        name = path.name
        extension = path.suffix.lower()
        kind: str | None = None

        if COMPOSE_NAME.match(name):
            kind = "compose"
        elif DOCKERFILE_NAME.match(name):
            kind = "dockerfile"
        elif name == FLY_NAME:
            kind = "fly"
        elif name == NETLIFY_NAME:
            kind = "netlify"
        elif name in RENDER_NAMES:
            kind = "render"
        elif name == HEROKU_NAME:
            kind = "heroku"
        elif extension in (".yml", ".yaml"):
            try:
                rel_candidate = path.relative_to(root).as_posix()
            except ValueError:
                rel_candidate = name
            if rel_candidate.startswith(".github/workflows/"):
                kind = "ci"

        if kind is None and extension not in (".yml", ".yaml"):
            continue

        try:
            if path.stat().st_size > 1024 * 1024:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if kind == "heroku":
            # app.json is also used by Expo and other tools; only a top-level
            # ``env`` mapping makes it a Heroku manifest.
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or not isinstance(payload.get("env"), dict):
                continue

        if kind is None:
            if K8S_KIND.search(text) and ("containers:" in text or "env:" in text):
                kind = "k8s"
            else:
                continue

        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = name

        partial = parse_manifest(text, rel, kind, path.parent)
        for key, sources in partial.keys.items():
            for source in sources:
                total.add(key, source)
        for key, sources in partial.ci_keys.items():
            for source in sources:
                total.add(key, source, ci=True)
        for unknown in partial.unknown:
            if unknown not in total.unknown:
                total.unknown.append(unknown)
        total.files.extend(partial.files)
        total.runtime_files.extend(partial.runtime_files)

    total.files = sorted(dict.fromkeys(total.files))
    total.runtime_files = sorted(dict.fromkeys(total.runtime_files))
    return total
