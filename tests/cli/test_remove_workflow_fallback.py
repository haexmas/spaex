"""T082 — retracting the adopted workflow molecule (Spec 011 amendment FR-008).

The bundled-speckit fallback is a Spec 011 concern that lands separately;
this test confirms `haex remove` correctly retracts the workflow molecule
from the manifest and the ensuing install completes without prompting for
any activation step.
"""

from __future__ import annotations

import json
from pathlib import Path

_CONST_ID = "com.example.publisher.const"
_WORKFLOW_ID = "com.example.publisher.workflow-adopted"


def test_workflow_molecule_can_be_retracted(
    tmp_path: Path, haex_add_helpers, monkeypatch
) -> None:
    canonical, head, state_root = haex_add_helpers["make_publisher"](
        tmp_path,
        {
            _CONST_ID: {
                "path": "const",
                "version": "1.0.0",
                "atoms": {"constitution": ["constitution.md"]},
            },
            _WORKFLOW_ID: {
                "path": "wf",
                "version": "1.0.0",
                "atoms": {"workflow": ["speckit.md"]},
            },
        },
    )
    consumer = haex_add_helpers["make_consumer"](tmp_path)
    haex_add_helpers["run_add"](
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        revision=head,
        all=True,
    )
    before = json.loads((consumer / ".haex-hive.json").read_text())
    assert _WORKFLOW_ID in before["compounds"][0]["molecules"]

    rc = haex_add_helpers["run_remove"](
        consumer, state_root, monkeypatch, molecule_ids=_WORKFLOW_ID
    )
    # No activation step is prompted; the retraction succeeds and install
    # publishes without the workflow molecule. Spec 011 FR-008's bundled
    # speckit fallback landing separately does not affect this outcome.
    assert rc == 0
    after = json.loads((consumer / ".haex-hive.json").read_text())
    assert _WORKFLOW_ID not in after["compounds"][0]["molecules"]
    assert _CONST_ID in after["compounds"][0]["molecules"]
