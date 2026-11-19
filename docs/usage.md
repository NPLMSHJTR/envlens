# CLI reference

Every command accepts `--root <dir>` (default: the current directory). Findings
are reported relative to that root, so a monorepo run and a single-service run
describe the same file the same way.

## `envlens check [PATH ...]`

Runs the full audit.

| Flag | Effect |
| --- | --- |
| `--example FILE` | Use this file as the contract. Repeatable; overrides discovery. |
| `--env-file FILE` | Compare against this local file. Repeatable; default `.env`, `.env.local`. |
| `--include GLOB` | Only scan paths matching the glob. |
| `--exclude GLOB` | Skip paths matching the glob. Paths named on the command line bypass this. |
| `--ignore GLOB` | Suppress findings for matching keys (`SENTRY_*`, `CI_*`). |
| `--no-manifests` | Skip Compose, Kubernetes, Dockerfile, and workflow analysis. |
| `--format text\|json\|github` | Output format. |
| `--fail-on error\|warning\|never` | Lowest severity that produces exit code 1. |
| `--color auto\|always\|never` | ANSI colour in text output. `NO_COLOR` is honoured. |

When no example file is discovered, the audit still reports every key read in
code as `missing-from-example` and prints a note suggesting `envlens init`. That
is intentional: an absent contract is the most severe form of drift.

## `envlens init [PATH ...]`

Writes an example file from the keys the scanner found. Every key gets a comment
naming up to two source locations. Existing files are never overwritten unless
`--force` is passed; `--dry-run` prints the result instead of writing it.

`init` writes code-referenced keys only. Keys that appear solely in a Compose
file or a Kubernetes manifest are not part of the application's contract, and
adding them would create `unused-in-code` noise on the next run.

## `envlens fix [PATH ...]`

Appends the keys that the primary example file is missing, under a generated
comment block. Existing lines are never reordered, reformatted, or removed,
because those lines usually carry hand-written explanations that a tool has no
business rewriting.

`fix` is idempotent: a second run reports that the contract already documents
every key.

## `envlens explain KEY`

Prints the declaration site, up to six read sites, the manifests that supply the
key, and the highest-severity finding attached to it. Exit code is `1` when the
key has an error-level finding or no evidence at all.

## Discovery rules

The audit looks for these names unless `--example` or `--env-file` says
otherwise:

- **Contract:** `.env.example`, `.env.sample`, `.env.template`, `.env.dist`,
  `example.env`
- **Local:** `.env`, `.env.local` — in the root and in each directory named on
  the command line

Discovery respects `exclude`, except for paths named explicitly on the command
line.

## Scanned languages

Python, JavaScript, TypeScript, Vue, Svelte, Astro, Go, Rust, Ruby, PHP, Java,
Kotlin, C#, Swift, Dart, Elixir, Scala, C/C++, Lua, R, Julia, Perl, Clojure.

| Language | Recognised forms |
| --- | --- |
| Python | `os.environ["K"]`, `os.environ.get("K")`, `os.getenv("K")`, `os.environ.setdefault("K", ...)` |
| JavaScript / TypeScript | `process.env.K`, `process.env["K"]`, `const { A, B } = process.env`, `import.meta.env.K`, `Deno.env.get("K")`, `Bun.env.K` |
| Go | `os.Getenv("K")`, `os.LookupEnv("K")` |
| Rust | `env::var("K")`, `env::var_os("K")` |
| Ruby | `ENV["K"]`, `ENV.fetch("K")` |
| PHP | `getenv("K")`, `$_ENV["K"]` |
| Java / Kotlin | `System.getenv("K")` |
| C# | `Environment.GetEnvironmentVariable("K")` |
| Swift | `ProcessInfo.processInfo.environment["K"]` |
| Dart | `Platform.environment["K"]`, `String.fromEnvironment("K")` |
| Elixir | `System.get_env("K")`, `System.fetch_env!("K")` |
| Scala | `sys.env("K")`, `sys.env.get("K")` |
| C / C++ | `getenv("K")`, `std::getenv("K")` |
| Lua | `os.getenv("K")` |
| R | `Sys.getenv("K")` |
| Julia | `ENV["K"]` |
| Perl | `$ENV{K}`, `$ENV{'K'}` |
| Clojure | `(System/getenv "K")` |

Add `# envlens:ignore` on a line, or on the comment line above it, to silence
that read. This is useful for keys whose names are assembled at runtime.

## Manifest coverage

| Format | What is read |
| --- | --- |
| Docker Compose | `environment:` mapping and list forms, `${VAR}` interpolation, `env_file` contents |
| Kubernetes | Container `env:` list entries, including `valueFrom` and `secretKeyRef` names |
| Dockerfile | `ARG` and `ENV` declarations |
| GitHub Actions | `env:` blocks, `${{ secrets.X }}`, `${{ vars.X }}` |
| Fly.io (`fly.toml`) | The `[env]` table |
| Render (`render.yaml`) | `envVars:` entries with a `key` field |
| Netlify (`netlify.toml`) | `[build.environment]` and `[context.*.environment]` |
| Heroku (`app.json`) | The top-level `env` mapping |

Fly.io, Netlify, and Heroku manifests are parsed with `tomllib` and `json`, so
their keys are exact rather than line-matched. A `render.yaml` is read line by
line inside its `envVars` block.

Workflow keys are tracked separately from runtime keys. A secret that CI knows
about is not evidence that the deployed container receives it, so workflow keys
never satisfy the `unprovisioned` rule.

## Configuration precedence

1. Command-line flags
2. `.envlens.toml` (or `[tool.envlens]` in `pyproject.toml`)
3. Built-in defaults

`include`, `exclude`, and `ignore` are additive between configuration and flags;
`example_files` and `local_files` are overridden by flags.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Threshold not crossed. |
| `1` | Threshold crossed, `init` refused to overwrite, or `explain` found an error. |
| `2` | Usage error: unknown path, invalid configuration, missing contract. |

## JSON schema

```json
{
  "schema_version": 1,
  "tool": { "name": "envlens", "version": "0.1.0" },
  "root": "/absolute/path",
  "summary": { "error": 13, "warning": 5, "info": 0, "files_scanned": 5, "dynamic_accesses": 2 },
  "findings": [
    {
      "rule": "missing-from-example",
      "severity": "error",
      "key": "SENTRY_DSN",
      "message": "read in code but not declared in any example file",
      "file": "src/app.py",
      "line": 9,
      "hint": "run `envlens fix` to append a placeholder, or add the key by hand"
    }
  ],
  "coverage": {
    "languages": { "Python": 1, "TypeScript": 1 },
    "skipped": { "binary": 1 },
    "dynamic": [{ "file": "src/app.py", "line": 13, "language": "Python" }]
  },
  "files": { "example": [".env.example"], "local": [".env"], "manifests": ["docker-compose.yml"] },
  "notes": []
}
```
