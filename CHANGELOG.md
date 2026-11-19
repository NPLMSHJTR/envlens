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
- Static scanning for 20 languages: Python, JavaScript, TypeScript, Go, Rust,
  Ruby, PHP, Java, Kotlin, C#, Swift, Dart, Elixir, Scala, C/C++, Lua, R, Julia,
  Perl, and Clojure, plus Vue, Svelte, and Astro component files and the Deno and
  Bun runtimes.
- Manifest parsing for Docker Compose, Kubernetes, Dockerfiles, GitHub Actions
  workflows, Fly.io, Render, Netlify, and Heroku, with CI keys tracked separately
  from runtime keys.
- A composite GitHub Action (`action.yml`) so non-Python repositories can run the
  audit without installing Python themselves.
- Text, JSON, and GitHub Actions output formats.
- Configuration through `.envlens.toml` or `[tool.envlens]`.
- Coverage reporting: scanned languages, skipped files by reason, and dynamic
  accesses that could not be resolved statically.
- 69 standard-library tests and a polyglot demo repository.
