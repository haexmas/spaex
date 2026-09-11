---
id: no-secrets-in-git
kind: constitution_fragment
atom_source: spaex.constitution
modality: MUST_NOT
tags: [security, secrets]
---
**MUST NOT** commit key material (SSH private keys, OAuth tokens, API keys, passwords, or encrypted-at-rest secret blobs) to git in any form, in the harness repo or any repo consuming its harness. Repos carry only references to identities, such as `identity: work-github`. Secrets live in the OS keychain of each device and move between devices only through the one-shot secret-provisioning path; the relay MUST NOT be used as a long-lived encrypted secret store. Encrypted secrets committed to git are effectively permanent (rotation is not deletion, and harvest-now-decrypt-later remains a live threat), so plaintext must never enter repository history in any form.
