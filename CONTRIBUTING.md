# Contributing

Thanks for taking the time to improve `envlens`. This document describes the
two changes people make most often, and the constraints that keep the tool
trustworthy.

## Development setup

No third-party package is required to run the test suite.

```bash
git clone https://github.com/NPLMSHJTR/envlens.git
cd envlens
python -m unittest discover -s tests -t tests -v
```

For linting and type checking:

```bash
python -m pip install -e ".[dev]"
ruff check .
mypy
```

## Ground rules

Three rules decide whether a change fits:

1. **Never guess.** A rule may only report what two parsed sources prove. If the
   evidence is incomplete, the output says so — a note, a dynamic-access count,
   or a skipped check — instead of producing a plausible finding.
2. **Never rewrite the user's file.** `fix` and `init` append. They do not
   reorder, reformat, or delete existing lines.
3. **No runtime dependencies.** The value of a zero-dependency CLI is that it
   installs in any CI image and cannot break because a transitive package moved.
   Standard library only, Python 3.11+.

## Adding a language

1. Add the extension to `EXT_LANGUAGE` in `src/envlens/scanner.py`.
2. Add one `_p(...)` entry per call form, with a `needle` that must appear in the
   line. The needle is what keeps large repositories fast.
3. Add a dynamic-access pattern when the key can be a variable rather than a
   literal. Reporting dynamic access is mandatory; silently ignoring it inflates
   the tool's apparent coverage.
4. Add a test in `tests/test_scanner.py` covering every literal form and the
   dynamic form.
5. Update the table in `docs/usage.md`.

Prefer two precise patterns over one clever one. A regex that also matches
`process.env` inside a comment is worse than a missing form, because false
confidence is the failure mode this tool exists to avoid.

## Adding a rule

1. Add the finding in `src/envlens/rules.py`, with a file and line whenever one
   exists.
2. Choose the severity by consequence, not by ease of detection: an error means
   production can break, a warning means documentation or hygiene is wrong.
3. Add a fixture under `tests/fixtures/` that isolates the rule, and assert both
   that it fires and that it stays quiet on `tests/fixtures/clean`.
4. Document the rule in the README table and in `docs/usage.md`.

## Changing output

The text format may change between minor versions. The JSON schema may not:
additive fields are fine, renames and removals require a `schema_version` bump.
The `github` format is a contract with GitHub Actions and must stay valid
workflow-command syntax.

## Tests

`tests/test_rules.py` asserts exact key sets against `examples/demo-service`.
That fixture is also the public demo, so a change to either one must keep the
documented numbers in the README true. If you add a finding to the demo, update
the README, this document, and the test in the same commit.

## Commit messages

Short imperative subject lines, for example `add Kotlin support to the scanner`.
Explain the reason in the body when the change is not self-evident.
