# Spec Kit integrations

Molecules may declare the official Spec Kit integrations they support without
shipping copies of Spec Kit skills:

```json
{
  "speckit": {
    "version_constraint": ">=0.8.1",
    "cli": {
      "package": "specify-cli",
      "version": "0.8.1"
    },
    "integrations": {
      "claude": { "integration_options": "--skills" },
      "codex": { "integration_options": "--skills" }
    }
  }
}
```

During `spaex install`, spaex provisions the exact `specify-cli` version via
the bundled `uv` dependency and `uv tool run`. Select integrations explicitly
with `--speckit-agents claude,codex`, choose interactively, or disable the step
for one invocation with `--no-speckit-integrations`. spaex delegates file layout,
managed-file conflicts, and agent-specific behavior to the installed official
`specify` CLI.

A repository that is not yet a Spec Kit project (no `.specify/` directory) is
bootstrapped first with `specify init --here --force --non-interactive`, using
the alphabetically first selected integration; the remaining selected
integrations are then installed as usual.

The exact CLI package version is part of the molecule declaration and is
installed into uv's isolated tool cache on first use. spaex does not modify the
user's PATH or install an agent runtime. Since the official CLI owns the
external agent files, removing a molecule warns about files that may remain;
spaex does not automatically uninstall them.
