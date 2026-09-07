# Contract: GitHub Actions release workflow

**Spec**: 014
**Location in code**: `.github/workflows/release.yml` (added in Phase 6)
**Trigger**: push of a tag matching `v*` (e.g., `v4.0.0`, `v4.0.1`, `v4.1.0`).

## Pre-flight requirements (one-time, manual)

The maintainer registered these on 2026-09-07:

- PyPI **project** `spaex` exists (via pending-publisher registration; the first successful publish creates the project record).
- PyPI **Trusted Publisher** entry pointing at:
  - Owner: `haexmas`
  - Repository: `haex-hive` until the GitHub-repo rename; update it to `spaex` before a post-rename release
  - Workflow filename: `release.yml`
  - Environment: `pypi`
- GitHub **Environment** `pypi` in `haexmas/haex-hive` repo settings until the GitHub-repo rename; update it to `haexmas/spaex` afterward. Optionally with a required-reviewer gate for manual approval before publish.

If any of these are missing at workflow-run time, the publish step fails with a PyPI OIDC error. No secret rotation needed; nothing to fix in the workflow itself.

## Workflow shape (contract)

```yaml
name: release
on:
  push:
    tags: ['v*']
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: python -m pip install --upgrade pip build
      - name: verify tag matches package version
        run: |
          package_version="$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
          test "$package_version" = "${GITHUB_REF_NAME#v}"
      - run: python -m build
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
  publish:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/p/spaex
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
```

## Build contract

- `python -m build` produces `dist/spaex-<version>.tar.gz` (sdist) and `dist/spaex-<version>-py3-none-any.whl` (pure-Python wheel).
- The `<version>` MUST match `pyproject.toml`'s `[project].version` at the tagged commit. The tag itself is `v<version>` (e.g., tag `v4.0.0` → version `4.0.0`).
- Before building, the workflow MUST read `[project].version` and fail unless it exactly matches `${GITHUB_REF_NAME#v}`. Prerelease and development versions may build for verification but MUST NOT reach the PyPI publish step.
- No cross-platform wheels; `spaex` is pure Python. If a native extension is ever added, this contract expands.

## Publish contract

- `pypa/gh-action-pypi-publish@release/v1` uses OIDC. No `password`, `user`, or `api-token` inputs are set. No `PYPI_API_TOKEN` secret is stored in the GitHub repo.
- Publish target is public PyPI. TestPyPI is not addressed by this workflow (may be added later).
- The `pypi` GitHub Environment MAY be configured with a required reviewer. When required-reviewer is on, the publish job pauses waiting for approval; the workflow does not fail while paused.

## Release procedure (out-of-band, once per release)

1. On `main`, edit `pyproject.toml`: `version = "4.0.0.dev0"` → `version = "4.0.0"`. Commit as `chore(release): 4.0.0`.
2. `git tag v4.0.0 && git push origin v4.0.0`.
3. Workflow triggers. Build job completes; publish job pauses if required-reviewer is on, else publishes directly.
4. Reviewer (if configured) approves in the GitHub Environments UI.
5. On successful publish, PyPI project page shows `spaex 4.0.0`.
6. Bump `main` version to `4.0.1.dev0`. Commit as `chore(release): open 4.0.1 cycle`.
7. Create GitHub Release: `gh release create v4.0.0 --generate-notes` (out-of-band, not part of the workflow).

## Failure modes and recovery

- **Build failure**: fix the underlying issue on `main`, cut a new patch tag (e.g., `v4.0.1`) and re-run. Do not force-move the original tag.
- **Publish failure due to name collision**: means the project name `spaex` was taken between pre-flight and first publish. Coordinate with PyPI support.
- **OIDC token failure**: usually a mismatched Trusted Publisher config. Verify the workflow filename, owner, repo, and environment match exactly.
- **Version already on PyPI**: PyPI refuses re-uploads of the same version. Bump the version and retag.
