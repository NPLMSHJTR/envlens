# Demo service

This directory is a small, deliberately broken polyglot repository. `envlens`
uses it in two ways: the test suite asserts exact findings against it, and the
README points readers at it as a runnable example.

Run the audit from the repository root:

```bash
PYTHONPATH=src python -m envlens check examples/demo-service
PYTHONPATH=src python -m envlens check examples/demo-service --format json
```

## What is wrong on purpose

| Problem | Where |
| --- | --- |
| Six keys are read in code but missing from `.env.example` | `src/*` |
| `LEGACY_FLAG` is documented but nothing reads it | `.env.example` |
| `STRIPE_SECRET_KEY` carries a credential-shaped value | `.env.example` |
| Four keys are read in code but supplied by no runtime manifest | `src/*` |
| Two local keys are undocumented, two documented keys are absent locally | `.env`, `.env.example` |

The code is nonsense on purpose. Nothing here is meant to run; it exists to give
the scanner realistic input in five languages plus three manifest formats.
