# Quickstart: external skill references

**Implementation status**: implemented end to end. The structured
`external_skills` reference below (molecule manifest side, User Stories 1-2)
parses, validates, and requires no `install_hook`. The consumer-side
`skill_installation` policy and the `spaex skills install`/`spaex skills
configure` commands (User Story 3) are implemented. The SHA below is a
placeholder; replace it with the full commit SHA containing the skill.

A publisher declares source metadata without an installation hook:

```json
{
  "spaex_version": "4",
  "id": "com.example.publisher.agent-tools",
  "version": "2.0.0",
  "priority": 100,
  "atoms": {"constitution": ["constitution.md"]},
  "external_skills": [
    {
      "repository": "https://github.com/haexmas/atoms",
      "revision": "0123456789abcdef0123456789abcdef01234567",
      "path": "skills/example-skill"
    }
  ]
}
```

The consumer-selected adapter reads the pinned molecule `manifest.json` via
`SPAEX_MOLECULE_MANIFEST`. Normal `spaex install` does not materialize or
install the reference; it only reports that references are pending. The
consumer explicitly runs `spaex skills install`, which prompts once (in an
interactive session) to choose a mode, adapter, scope, and agents, then
persists that choice under `skill_installation` in `.spaex/manifest.json`
before running the adapter. Later changes use `spaex skills configure`,
which edits the same policy but never runs an adapter.

`skill_installation.mode` is one of `prompt` (ask every time), `managed`
(remember the choice and run without asking), or `disabled` (report pending
references and do nothing else). `adapter` names an executable spaex
resolves on `PATH` and invokes once per molecule with pending skills, with
`cwd` set to the repository root and `SPAEX_MOLECULE_MANIFEST` pointing at
that molecule's own pinned `manifest.json`; spaex does not synthesize any
other argv from `scope`/`agents`, so an adapter that needs them reads the
persisted policy itself from `.spaex/manifest.json`. `adapter: "manual"` is
a reserved value meaning the consumer installs by hand; spaex does not
launch a subprocess for it.

The skill may live in the same `haexmas/atoms` repository as the molecule.
The reference is metadata for spaex: spaex itself does not copy it into the
consumer repository. The explicitly selected installer owns the external
skill lifecycle, while the skill content remains outside spaex's install lock.
