# Publishing checklist

The repository is ready to publish as-is. Four items depend on the final owner
and should be completed on the first push.

## 1. Confirm the remote

```bash
git remote add origin https://github.com/<owner>/envlens.git
git push -u origin main
```

The README and `CONTRIBUTING.md` already point at
`https://github.com/NPLMSHJTR/envlens`. Change both if the repository moves.

## 2. Repository metadata

Description to use:

> Static audit of environment variables across source code, .env files, and deployment manifests.

Suggested topics:

```
dotenv  environment-variables  linter  static-analysis  devops  ci  docker-compose  kubernetes  python-cli
```

Enable "Issues" and "Discussions"; disable "Wiki", because the documentation
lives in `docs/`.

## 3. PyPI

The name `envlens` was free on PyPI when this checklist was written; confirm
before publishing.

```bash
python -m pip install build twine
python -m build
twine check dist/*
twine upload dist/*
```

Building requires `hatchling`, which `pyproject.toml` declares. The wheel
contains `src/envlens` only; tests and examples stay in the sdist by default.

## 4. Post-publish edits

- Add a PyPI badge and change the install section from "from a checkout" to
  `pipx install envlens`.
- Replace the measured-results table when the numbers change; they describe one
  machine and one commit, and they should never be copied forward unmeasured.
- Add a `CHANGELOG.md` entry for every release, and tag releases with the same
  version as `pyproject.toml`.
