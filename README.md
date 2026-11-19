# envlens

**Your `.env.example` is a promise. `envlens` checks whether your code, your local
env file, and your deployment manifests actually keep it.**

`envlens` is a zero-dependency command-line audit for environment variables. It
reads four things — the keys your source code reads, the keys your example file
declares, the keys your local `.env` defines, and the keys your manifests supply
— and reports every disagreement with a file and line number.

```console
$ envlens check .
ERROR   missing-from-example (7) — read in code but not declared in any example file
  SENTRY_DSN           src/app.py:9
  GITHUB_TOKEN         src/worker.go:9
  ...

ERROR   unprovisioned (5) — read in code but supplied by no runtime manifest
  OTEL_ENDPOINT        src/db.ts:2
  ...

WARNING unused-in-code (1) — declared in the example file but no scanned source reads it
  LEGACY_FLAG          .env.example:8

13 errors · 5 warnings · 0 info
5 files scanned (Python 1, TypeScript 1, Ruby 1, Rust 1, Go 1)
```

## Why this exists

A `.env.example` file is documentation that nothing executes, so it drifts. A
developer adds `SENDGRID_API_KEY` to their local `.env`, ships the feature, and
never updates the example, because the feature already works on their machine.
Three weeks later a new teammate clones the repository, copies the example, and
the process dies on a missing key — or worse, boots with a feature silently
disabled.

Runtime validators such as `envalid`, `zod`, or `pydantic-settings` do not close
this gap. They validate the environment the process actually received; they
cannot tell you that the example file forgot a key, because the example file is
not part of the build graph.

`envlens` closes the gap statically, before anything runs, and it extends the
check one step further: a key can be documented, read by code, and still never
reach the container, because `docker-compose.yml` or the Kubernetes manifest
never learned about it.

## What it checks

| Rule | Default severity | What it means |
| --- | --- | --- |
| `missing-from-example` | error | The code reads a key that no example file declares. |
| `unused-in-code` | warning | An example file declares a key that no scanned source reads. |
| `local-missing` | warning | The example declares a key that the local env file lacks. |
| `local-extra` | warning | The local env file defines a key the example never documents. |
| `unprovisioned` | error | The code reads a key that no runtime manifest supplies. |
| `secret-in-example` | error | An example file contains a credential-shaped value. |
| `duplicate-key` | warning | A dotenv file declares the same key twice. |
| `invalid-line` | warning | A line is neither a comment nor an assignment. |
| `case-collision` | warning | Two keys differ only by case and collide in POSIX shells. |

Nine rules, thirteen languages, and four manifest formats. Nothing in the list
requires a schema file, an annotation, or a change to your application code.

## Install

`envlens` is not on PyPI yet. Install it from a checkout:

```bash
git clone https://github.com/NPLMSHJTR/envlens.git
cd envlens
pipx install .
```

`pipx` keeps the CLI isolated; plain `pip install .` works too. The only runtime
requirement is Python 3.11 or newer. There are no third-party dependencies, so
the install cannot break because a transitive package changed.

## Quick start

```bash
cd your-project

# 1. See what is wrong today.
envlens check

# 2. Generate a first contract from the code (only when no example exists).
envlens init

# 3. Append the keys the contract is missing, without touching existing lines.
envlens fix

# 4. Understand one variable end to end.
envlens explain SENTRY_DSN
```

`explain` prints every fact the audit has about a key:

```console
$ envlens explain DATABASE_URL
DATABASE_URL
  declared     .env.example:2
  read in code src/app.py:7, src/db.ts:1
  provisioned  docker-compose.yml, deploy/app.yaml
  status       ok
```

## Output formats

```bash
envlens check --format text      # grouped, human readable (default)
envlens check --format json      # versioned schema for tooling
envlens check --format github    # ::error annotations on the pull request diff
```

The JSON payload is stable and includes the coverage data that the text output
compresses: which languages were scanned, which files were skipped and why, and
every dynamic access the scanner could not resolve.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | No finding at or above the configured threshold. |
| `1` | A finding crossed the threshold, or a repair command refused to overwrite. |
| `2` | The tool could not run: bad path, bad configuration, missing contract. |

`--fail-on error` is the default; `--fail-on warning` makes CI stricter;
`--fail-on never` reports without failing.

## Use it in CI

```yaml
name: env-contract
on: [pull_request]

jobs:
  envlens:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install .
      - run: envlens check --format github --fail-on warning
```

The `github` format emits workflow commands, so failures annotate the exact line
in the diff instead of hiding in a log.

For pre-commit:

```yaml
repos:
  - repo: local
    hooks:
      - id: envlens
        name: envlens
        entry: envlens check --fail-on warning
        language: system
        pass_filenames: false
```

## Configuration

Put a `.envlens.toml` at the repository root, or a `[tool.envlens]` table in
`pyproject.toml`:

```toml
[tool.envlens]
example_files = [".env.example", "services/api/.env.example"]
exclude = ["vendor/**", "tests/fixtures/**"]
ignore = ["CI_*", "SENTRY_*"]
fail_on = "warning"
```

Command-line arguments win over configuration, and explicitly named paths win
over `exclude`: `envlens check services/api` audits that directory even when the
configuration excludes it from a full-tree run.

## What it deliberately does not do

Static analysis earns trust by admitting where it stops. `envlens` does not:

- **Resolve computed keys.** `process.env[someVariable]` and
  `os.environ[name]` cannot be known without running the program. They are
  counted as dynamic accesses and reported in the coverage line, never guessed.
- **Parse every language.** Python, JavaScript/TypeScript, Vue, Svelte, Astro,
  Go, Rust, Ruby, PHP, Java, Kotlin, and C# are scanned. A key read only by, say,
  a Swift or Elixir file is invisible to this tool; the `unused-in-code` warning
  therefore says "no scanned source reads it", not "nothing reads it".
- **Read values for comparison.** Presence is compared, not content. The one
  exception is `secret-in-example`, which pattern-matches credential shapes in
  files that are meant to be committed.
- **Guess at unreadable provisioning.** When a Compose file references an
  `env_file` that is not in the repository, or a Kubernetes manifest uses
  `envFrom`, the `unprovisioned` rule is skipped and a note explains why. An
  unknown source is not the same as an absent one.
- **Touch the network.** The tool reads local files and writes local reports.
  Nothing is uploaded, and there is no telemetry.

## Prior art

Several good tools cover neighbouring ground. The comparison below reflects each
project's own README and repository metadata on 19 November 2026.

| Tool | Scope | Difference from `envlens` |
| --- | --- | --- |
| `dotenv-linter` (Rust, 2,119 stars) | Lints dotenv syntax and ordering | Does not read source code or manifests |
| `dotenv-diff` (Node, 86 stars) | Compares JS/TS references against `.env` files | Limited to the JavaScript ecosystem |
| `sync-dotenv` (Node, 477 stars) | Keeps `.env` and `.env.example` aligned | Two-file comparison only; last push March 2023 |
| `vaar` (Go, 31 stars) | `lint` and `diff` for dotenv files | Source-code and manifest analysis are listed as roadmap, not shipped |

`envlens` occupies the intersection none of them cover: one static pass across
polyglot source, dotenv files, and deployment manifests, with coverage reported
rather than assumed.

## Measured results

These numbers come from one Windows 11 machine with Python 3.13.14 and a warm
file cache. They describe this implementation, not a promise about yours.

| Measurement | Result |
| --- | --- |
| Test suite | 61 tests, all passing |
| Audit of 3,000 generated source files | 0.768 s median (≈3,900 files/s) |
| CLI start-up (`envlens --version`) | 0.356 s median |
| Own repository (`envlens check .`) | 11 files, no findings |

## Try the demo

`examples/demo-service` is a deliberately broken mini-repository in five
languages with a Compose file, a Kubernetes manifest, a Dockerfile, and a
workflow. It produces exactly the findings quoted at the top of this file:

```bash
envlens check examples/demo-service
```

## Development

```bash
python -m unittest discover -s tests -t tests   # no dependencies needed
python -m pip install -e ".[dev]"               # ruff and mypy, optional
```

The test suite uses only the standard library, so it runs anywhere Python 3.11
runs, including a bare CI container.

## License

MIT. See [LICENSE](LICENSE).

## References

"dotenv-diff." *GitHub*, Chrilleweb, 19 Nov. 2026,
github.com/Chrilleweb/dotenv-diff.

"dotenv-linter." *GitHub*, dotenv-linter, 19 Nov. 2026,
github.com/dotenv-linter/dotenv-linter.

"sync-dotenv." *GitHub*, luqmanoop, 19 Nov. 2026,
github.com/luqmanoop/sync-dotenv.

"vaar." *GitHub*, envaar, 19 Nov. 2026, github.com/envaar/vaar.
