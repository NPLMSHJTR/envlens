"""Command-line interface.

Four commands share one audit core:

``check``    reports findings and sets the exit code used by CI
``init``     generates a first ``.env.example`` from the code
``fix``      appends keys that the contract is missing
``explain``  shows every fact known about one variable

Exit codes are part of the contract: ``0`` means the configured threshold was
not crossed, ``1`` means it was, and ``2`` means the tool could not run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import Config, load_config
from .dotenv import load_dotenv
from .fix import append_to_example, render_append, render_example, write_example
from .model import Severity
from .report import FORMATS, exit_code, render, use_color
from .rules import (
    DEFAULT_EXAMPLES,
    Options,
    audit,
    discover_examples,
)
from .scanner import scan_paths

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def _resolve_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"root is not a directory: {value}")
    return root


def _resolve_targets(root: Path, targets: list[str]) -> list[str]:
    resolved = targets or ["."]
    for target in resolved:
        if not (root / target).exists():
            raise ValueError(f"path does not exist under the root: {target}")
    return resolved


def _display_path(root: Path, path: Path) -> str:
    """Return a POSIX-style path relative to the root when possible."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _merged_options(args: argparse.Namespace, config: Config, root: Path) -> Options:
    examples = list(args.example or []) or list(config.example_files)
    locals_ = list(getattr(args, "env_file", None) or []) or list(config.local_files)
    include = list(getattr(args, "include", None) or []) or list(config.include)
    exclude = list(config.exclude) + list(getattr(args, "exclude", None) or [])
    ignore = list(config.ignore) + list(getattr(args, "ignore", None) or [])

    manifests = config.manifests if config.manifests is not None else True
    if getattr(args, "manifests", None) is not None:
        manifests = bool(args.manifests)

    fail_on = getattr(args, "fail_on", None) or config.fail_on or "error"
    if fail_on not in ("error", "warning", "never"):
        raise ValueError(f"fail-on must be error, warning, or never (got {fail_on!r})")

    return Options(
        root=root,
        targets=_resolve_targets(root, list(args.paths)),
        example_files=examples,
        local_files=locals_,
        include=include,
        exclude=exclude,
        ignore=ignore,
        manifests=manifests,
        fail_on=fail_on,
    )


def cmd_check(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    config = load_config(root)
    options = _merged_options(args, config, root)
    report = audit(options)
    color = use_color(args.color) if args.format == "text" else False
    sys.stdout.write(render(report, args.format, color))
    return exit_code(report, options.fail_on)


def cmd_init(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    config = load_config(root)
    options = _merged_options(args, config, root)
    used, coverage = scan_paths(root, options.targets, options.exclude, options.include)
    content = render_example(used)
    destination = (root / args.output).resolve()

    if args.dry_run:
        sys.stdout.write(content)
        return EXIT_OK

    state = write_example(destination, content, force=args.force)
    rel = _display_path(root, destination)
    if state == "skipped":
        print(f"envlens: {rel} already exists; pass --force to overwrite", file=sys.stderr)
        return EXIT_FINDINGS
    print(f"envlens: {state} {rel} with {len(used)} key(s) from {coverage.files_scanned} file(s)")
    return EXIT_OK


def cmd_fix(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    config = load_config(root)
    options = _merged_options(args, config, root)
    examples, missing = discover_examples(
        root, options.targets, options.example_files, options.exclude
    )
    if missing:
        raise ValueError("example file not found: " + ", ".join(missing))
    if not examples:
        raise ValueError("no example file found; run `envlens init` first")

    primary = examples[0]
    declared = set(load_dotenv(primary).key_map)
    used, _ = scan_paths(root, options.targets, options.exclude, options.include)
    pending = [key for key in used if key not in declared]

    content = render_append(pending, used)
    rel = _display_path(root, primary)
    if not pending:
        print(f"envlens: {rel} already documents every key read in code")
        return EXIT_OK
    if args.dry_run:
        sys.stdout.write(content)
        return EXIT_OK

    append_to_example(primary, content)
    print(f"envlens: appended {len(pending)} key(s) to {rel}")
    return EXIT_OK


def cmd_explain(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    config = load_config(root)
    options = _merged_options(args, config, root)
    report = audit(options)
    key = args.key

    declared = report.declared.get(key, [])
    refs = report.used.get(key, [])
    provisioned = report.provisioned.get(key, [])
    related = [finding for finding in report.sorted_findings() if finding.key == key]

    if not declared and not refs and not provisioned:
        print(f"envlens: no evidence of {key} in {report.root}", file=sys.stderr)
        return EXIT_FINDINGS

    lines = [f"{key}"]
    if declared:
        locations = ", ".join(f"{file}:{line}" for file, line in declared)
        lines.append(f"  declared     {locations}")
    else:
        lines.append("  declared     (nowhere)")
    if refs:
        lines.append("  read in code " + ", ".join(ref.location for ref in refs[:6]))
    if provisioned:
        lines.append("  provisioned  " + ", ".join(provisioned[:4]))
    status = "ok" if not related else related[0].severity.name
    lines.append(f"  status       {status}")
    for finding in related:
        lines.append(f"  - {finding.rule}: {finding.message}")
    print("\n".join(lines))
    return EXIT_FINDINGS if any(f.severity is Severity.error for f in related) else EXIT_OK


def _add_common(parser: argparse.ArgumentParser, *, locals_: bool = False) -> None:
    parser.add_argument("paths", nargs="*", help="files or directories to scan (default: .)")
    parser.add_argument("--root", default=".", help="repository root (default: current directory)")
    parser.add_argument(
        "--example",
        action="append",
        metavar="FILE",
        help="example file that defines the contract (repeatable)",
    )
    if locals_:
        parser.add_argument(
            "--env-file",
            action="append",
            metavar="FILE",
            help="developer env file to compare against (repeatable, default: .env)",
        )
    parser.add_argument(
        "--include", action="append", metavar="GLOB", help="only scan matching paths"
    )
    parser.add_argument("--exclude", action="append", metavar="GLOB", help="skip matching paths")
    parser.add_argument("--ignore", action="append", metavar="GLOB", help="ignore matching keys")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="envlens",
        description=(
            "Audit environment variables across source code, .env files, and deployment manifests."
        ),
    )
    parser.add_argument("--version", action="version", version=f"envlens {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="report findings and set an exit code")
    _add_common(check, locals_=True)
    check.add_argument("--format", choices=FORMATS, default="text", help="output format")
    check.add_argument(
        "--fail-on",
        choices=("error", "warning", "never"),
        default=None,
        help="lowest severity that makes the command exit 1 (default: error)",
    )
    check.add_argument(
        "--no-manifests",
        dest="manifests",
        action="store_const",
        const=False,
        default=None,
        help="skip Docker Compose, Kubernetes, Dockerfile, and workflow analysis",
    )
    check.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="ANSI colour in text output (default: auto)",
    )
    check.set_defaults(func=cmd_check)

    init = subparsers.add_parser("init", help="generate an example file from the code")
    _add_common(init)
    init.add_argument("--output", default=DEFAULT_EXAMPLES[0], help="file to write")
    init.add_argument("--force", action="store_true", help="overwrite an existing file")
    init.add_argument("--dry-run", action="store_true", help="print instead of writing")
    init.set_defaults(func=cmd_init)

    fix = subparsers.add_parser("fix", help="append keys missing from the example file")
    _add_common(fix)
    fix.add_argument("--dry-run", action="store_true", help="print instead of writing")
    fix.set_defaults(func=cmd_fix)

    explain = subparsers.add_parser("explain", help="show every fact known about one variable")
    explain.add_argument("key", help="variable name to explain")
    _add_common(explain, locals_=True)
    explain.add_argument(
        "--no-manifests",
        dest="manifests",
        action="store_const",
        const=False,
        default=None,
    )
    explain.set_defaults(func=cmd_explain)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ValueError as error:
        print(f"envlens: {error}", file=sys.stderr)
        return EXIT_USAGE
    except BrokenPipeError:
        return EXIT_OK
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
