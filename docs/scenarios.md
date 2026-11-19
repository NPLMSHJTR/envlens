# Typical scenarios

Each scenario below was run against the repository in this checkout or against
the demo in `examples/demo-service`; the quoted output is real.

## 1. A new teammate clones the repository

The failure this catches is the expensive one: the clone builds, starts, and
dies on a key nobody documented, three weeks after the key was introduced.

```bash
git clone <repo> && cd <repo>
envlens check
```

On a repository with a stale contract the audit lists every key the code reads
but the example never mentions, with the line that reads it. The new teammate
knows what to ask for before running anything, and the maintainer gets a
concrete list instead of "it doesn't work".

If the repository has no example file at all, `envlens init` produces one from
the code, with a comment naming the file and line behind each key.

## 2. A pull request gate

The cheapest place to stop drift is the pull request that introduces it.

```yaml
- run: envlens check --format github --fail-on warning
```

Because the GitHub format emits workflow commands, the failing check annotates
`src/monitor.ts:14` directly in the diff. A reviewer sees "this line reads
`SENTRY_DSN`, and the example file does not declare it" without opening a log.

Severity choice matters here. `--fail-on error` blocks only broken contracts;
`--fail-on warning` also blocks undocumented or unused keys. Teams adopting the
tool on a legacy repository usually start with `--fail-on error` and tighten it
after the first cleanup.

## 3. The key exists everywhere except the container

This is the case two-file comparisons cannot see. A key can be declared in
`.env.example`, read in code, and absent from `docker-compose.yml`; local
development works and the first deploy fails.

```bash
envlens check --fail-on error
```

```console
ERROR   unprovisioned (5) — read in code but supplied by no runtime manifest
  OTEL_ENDPOINT        src/db.ts:2
```

The rule only runs when at least one runtime manifest exists, and it refuses to
run when a manifest defers to a source the tool cannot read. A Compose file that
points at a missing `env_file`, or a Kubernetes manifest that uses `envFrom`,
produces a note instead of a guess:

```console
note: provisioning check skipped: docker-compose.yml (env_file not found: .env.missing) cannot be resolved statically
```

## 4. Incident review: "where does this variable actually come from?"

`explain` answers the question in one command, without grepping four file types.

```console
$ envlens explain STRIPE_SECRET_KEY
STRIPE_SECRET_KEY
  declared     .env.example:11
  read in code src/db.ts:3
  status       error
  - secret-in-example: value looks like a real credential (Stripe live secret key)
  - unprovisioned: read in code but supplied by no runtime manifest
  - local-missing: declared in the example file but absent from the local env file
```

The status line is the highest-severity finding attached to that key, so the
answer to "is this safe to ship" is visible before the details.

## 5. Monorepo with per-service contracts

Services usually keep their own `.env.example` next to their code. Naming the
directories explicitly audits each one against its own contract:

```bash
envlens check services/api services/worker
```

Explicit paths bypass `exclude`, which means a directory excluded from the
full-tree run is still audited when someone asks for it by name. This is the
difference between a silent no-op and a useful answer.

For a stable setup, pin the contracts in configuration instead:

```toml
[tool.envlens]
example_files = ["services/api/.env.example", "services/worker/.env.example"]
exclude = ["vendor/**", "**/node_modules/**"]
```

## 6. Cleaning up after a migration

Removing a feature rarely removes its configuration. `unused-in-code` lists the
keys that the example still advertises but no scanned source reads:

```console
WARNING unused-in-code (1) — declared in the example file but no scanned source reads it
  LEGACY_FLAG          .env.example:8
```

The warning is deliberately not an error, because a key can be read by a
language the scanner does not parse or by an external image. Treat the list as a
review queue, not a delete list.

## 7. Adopting the tool on a large legacy repository

A first run on a ten-year-old repository can produce hundreds of findings, which
is useful once and unbearable in CI. Two mechanisms keep adoption gradual:

```bash
# Report everything, fail on nothing, while the team triages.
envlens check --fail-on never --format json > env-audit.json

# Silence whole families of keys that belong to the platform, not the app.
envlens check --ignore "CI_*" --ignore "KUBERNETES_*" --fail-on error
```

The JSON report is the input for a spreadsheet or an issue tracker; the ignore
list is the escape hatch for keys whose ownership sits outside the repository.
