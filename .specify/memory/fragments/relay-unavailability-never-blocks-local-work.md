---
id: relay-unavailability-never-blocks-local-work
kind: constitution_fragment
atom_source: spaex.constitution
modality: MUST_NOT
tags: [resilience, relay]
---
The Nostr relay serves only the liveness plane: status, commands, session refs, one-shot secret provisioning. Its unreachability **MUST NOT** prevent an agent CLI on a satellite from doing local work against local disk; only mobile visibility and control pause. All spec content, harness content, and project state MUST resolve from git and local files, not from the relay, because autonomous satellites exist precisely to keep working when the network doesn't.
