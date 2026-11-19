# Security policy

## Reporting a vulnerability

Open a private security advisory through GitHub, or email the maintainer listed
on the repository profile. Please do not open a public issue for a vulnerability.

Include the version, the command that triggers the problem, and the smallest
input that reproduces it. A response is intended within seven days.

## Scope

`envlens` reads files and prints reports. It does not open sockets, download
anything, or execute project code. The realistic risks are therefore:

- **Secret exposure in output.** Findings quote key names and file paths, never
  values. If you find a path where a value reaches stdout, stderr, or the JSON
  payload, that is a vulnerability and should be reported as one.
- **Path traversal through manifests.** Compose `env_file` entries are resolved
  relative to the manifest and rejected when they escape the repository root.
  A bypass of that check is a vulnerability.
- **Denial of service through crafted input.** The scanner caps file size at
  2 MiB and truncates lines at 4,000 characters. A regular expression that
  backtracks catastrophically on realistic input is a bug worth reporting.

## Out of scope

- Findings that are wrong because a project uses a language the scanner does not
  support. The limitation is documented, and the coverage line reports it.
- Credential-shaped strings in a file that is intentionally committed as a test
  fixture. Add `# envlens:ignore` or an `ignore` pattern instead.
