---
id: device-independent-project-identity
kind: constitution_fragment
atom_source: atoms.spaex-constitution
modality: MUST
tags: [identity, portability]
---
A project's identity **MUST** be its git remote URL, or, for a non-git folder project, an opaque id file (`.harness-id`) inside the folder, never a filesystem path. When one satellite addresses another, the addressing unit **MUST** be `(device-pubkey, project-identity)`, never a raw path. Path resolution is strictly a local, private concern of the device that owns the copy; raw paths that cross a device boundary are always a mistake.
