# Quickstart: external skill references

**Implementation status**: the structured `external_skills` reference below
(molecule manifest side, User Stories 1-2) is implemented: it parses,
validates, and requires no `install_hook`. The consumer-side
`skill_installation` policy and the `spaex skills install`/`spaex skills
configure` commands (User Story 3) are not implemented yet. The SHA below is
a placeholder; replace it with the full commit SHA containing the skill.

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
install the reference. The consumer will explicitly run `spaex skills install`,
choose an adapter,
agent, and scope on first use, and spaex stores that choice in
`.spaex/manifest.json`. Later changes use `spaex skills configure`.

The skill may live in the same `haexmas/atoms` repository as the molecule.
The reference is metadata for spaex: spaex itself does not copy it into the
consumer repository. The explicitly selected installer owns the external
skill lifecycle, while the skill content remains outside spaex's install lock.
