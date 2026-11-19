"""Configuration loading for ``.envlens.toml`` and ``pyproject.toml``.

Configuration exists so that a repository can state its own contract once
instead of repeating six flags in every CI job. Command-line arguments always
win over configuration; configuration always wins over built-in defaults.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILENAME = ".envlens.toml"
KNOWN_KEYS = {
    "example_files",
    "local_files",
    "include",
    "exclude",
    "ignore",
    "manifests",
    "fail_on",
}


@dataclass(slots=True)
class Config:
    """Values that a repository has pinned in its configuration file."""

    source: str | None = None
    example_files: list[str] = field(default_factory=list)
    local_files: list[str] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    ignore: list[str] = field(default_factory=list)
    manifests: bool | None = None
    fail_on: str | None = None


def _as_str_list(value: object, key: str, source: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise ValueError(f"{source}: '{key}' must be a string or a list of strings")


def _from_table(table: dict[str, object], source: str) -> Config:
    unknown = sorted(set(table) - KNOWN_KEYS)
    if unknown:
        raise ValueError(f"{source}: unknown keys: {', '.join(unknown)}")
    config = Config(source=source)
    config.example_files = _as_str_list(table.get("example_files"), "example_files", source)
    config.local_files = _as_str_list(table.get("local_files"), "local_files", source)
    config.include = _as_str_list(table.get("include"), "include", source)
    config.exclude = _as_str_list(table.get("exclude"), "exclude", source)
    config.ignore = _as_str_list(table.get("ignore"), "ignore", source)
    if "manifests" in table:
        if not isinstance(table["manifests"], bool):
            raise ValueError(f"{source}: 'manifests' must be a boolean")
        config.manifests = table["manifests"]
    if "fail_on" in table:
        if not isinstance(table["fail_on"], str):
            raise ValueError(f"{source}: 'fail_on' must be a string")
        config.fail_on = table["fail_on"]
    return config


def load_config(root: Path) -> Config:
    """Load configuration from ``.envlens.toml``, else ``pyproject.toml``."""
    dedicated = root / CONFIG_FILENAME
    if dedicated.is_file():
        with dedicated.open("rb") as handle:
            data = tomllib.load(handle)
        table = data.get("envlens", data)
        if not isinstance(table, dict):
            raise ValueError(f"{CONFIG_FILENAME}: top level must be a table")
        return _from_table(table, CONFIG_FILENAME)

    project = root / "pyproject.toml"
    if project.is_file():
        with project.open("rb") as handle:
            data = tomllib.load(handle)
        tool = data.get("tool", {})
        table = tool.get("envlens") if isinstance(tool, dict) else None
        if isinstance(table, dict):
            return _from_table(table, "pyproject.toml [tool.envlens]")

    return Config()
