# Changelog

All notable changes are recorded here. The format follows Keep a Changelog, and
the project adheres to Semantic Versioning.

## [0.1.0] - 2026-11-19

### Added

- `check` command with nine rules: `missing-from-example`, `unused-in-code`,
  `local-missing`, `local-extra`, `unprovisioned`, `secret-in-example`,
  `duplicate-key`, `invalid-line`, and `case-collision`.
- `init` command that generates an example file from code references.
- `fix` command that appends missing keys without modifying existing lines.
- `explain` command that reports every known fact about one variable.
- Static scanning for Python, JavaScript, TypeScript, Vue, Svelte, Astro, Go,
  Rust, Ruby, PHP, Java, Kotlin, and C#.
- Manifest parsing for Docker Compose, Kubernetes, Dockerfiles, and GitHub
  Actions workflows, with CI keys tracked separately from runtime keys.
- Text, JSON, and GitHub Actions output formats.
- Configuration through `.envlens.toml` or `[tool.envlens]`.
- Coverage reporting: scanned languages, skipped files by reason, and dynamic
  accesses that could not be resolved statically.
- 61 standard-library tests and a polyglot demo repository.
