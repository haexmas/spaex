"""T019-T022 - integration tests for Spec 016 User Story 1 (MVP happy path)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.cli import add as add_cli
from spaex.cli import install as install_cli
from spaex.migrate.transform import clone_dir
from spaex.model.install_lock import InstallLock

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)

_MOLECULE_ID = "com.example.publisher.hellohook"
_CANONICAL = "https://example.invalid/example/publisher"
_GITIGNORE_LINE = "graphify-out/"
_HOOK_SCRIPT = f'''#!/usr/bin/env python3
"""Idempotent gitignore-append install-hook (Spec 016 MVP fixture)."""
from pathlib import Path
import sys

LINE = {_GITIGNORE_LINE!r}
repo = Path.cwd()
gitignore = repo / ".gitignore"
existing = (
    gitignore.read_text(encoding="utf-8").splitlines()
    if gitignore.exists()
    else []
)
if LINE not in {{line.strip() for line in existing}}:
    with gitignore.open("a", encoding="utf-8") as fh:
        if existing and existing[-1] != "":
            fh.write("\\n")
        fh.write(f"{{LINE}}\\n")
    print(f"appended {{LINE}} to .gitignore")
else:
    print(f"{{LINE}} already present")

sys.exit(0)
'''


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _publish_hook_molecule(
    tmp_path: Path,
    *,
    on_failure: str = "abort",
    hook_body: str = _HOOK_SCRIPT,
) -> tuple[str, str, Path]:
    """Create a bare publisher clone whose one molecule declares install_hook."""
    working = tmp_path / "publisher-working"
    working.mkdir()
    _git(working, "init", "-q", "-b", "main")
    _git(working, "config", "user.email", "author@example.com")
    _git(working, "config", "user.name", "author")
    _git(working, "config", "commit.gpgsign", "false")

    (working / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "publisher": "com.example.publisher",
                "molecules": {
                    _MOLECULE_ID: {"path": "hello-hook", "version": "1.0.0"},
                },
            },
            indent=2,
        )
    )

    mol_dir = working / "hello-hook"
    mol_dir.mkdir()
    (mol_dir / "manifest.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "id": _MOLECULE_ID,
                "version": "1.0.0",
                "priority": 20,
                "atoms": {"constitution": ["constitution.md"]},
                "install_hook": {
                    "interpreter": sys.executable,
                    "script": "install.py",
                    "on_failure": on_failure,
                },
            },
            indent=2,
        )
    )
    (mol_dir / "constitution.md").write_text(
        "# Principle: hello-hook demo\n\nGoverned by Spec 016 MVP.\n"
    )
    (mol_dir / "install.py").write_text(hook_body)

    _git(working, "add", ".")
    _git(working, "commit", "-q", "-m", "hello-hook 1.0.0 with install_hook")
    head = _git(working, "rev-parse", "HEAD")

    state_root = tmp_path / "state"
    target = clone_dir(state_root, _CANONICAL)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(working), str(target)], check=True
    )
    return _CANONICAL, head, state_root


def _make_consumer(tmp_path: Path) -> Path:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / ".spaex.json").write_text(
        json.dumps(
            {
                "spaex_version": "4",
                "identity": "com.example.project-consumer",
                "compounds": [],
            }
        )
    )
    (consumer / ".harness-id").write_text("com.example.project-consumer")
    return consumer


def _run_add(
    consumer: Path,
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_url: str,
    molecule_ids: str = _MOLECULE_ID,
    revision: str,
) -> int:
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(
        repo_root=str(consumer),
        source_url=source_url,
        molecule_ids=molecule_ids,
        revision=revision,
        all=False,
        lock_timeout=5.0,
    )
    return add_cli.run(ns)


def _run_install(
    consumer: Path,
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    monkeypatch.setenv("SPAEX_STATE", str(state_root))
    ns = SimpleNamespace(repo_root=str(consumer), lock_timeout=5.0)
    return install_cli.run(ns)


def _read_lock(consumer: Path) -> InstallLock:
    return InstallLock.from_json(
        (consumer / ".spaex" / "install.lock").read_bytes()
    )


# --- T019 AS1 -------------------------------------------------------------


def test_hook_runs_after_atoms_and_writes_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AS1: hook runs after atoms materialize, gitignore has line once, hook_status ok."""
    canonical, head, state_root = _publish_hook_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    rc = _run_add(
        consumer,
        state_root,
        monkeypatch,
        source_url=canonical,
        revision=head,
    )
    assert rc == 0

    gitignore = (consumer / ".gitignore").read_text(encoding="utf-8")
    assert gitignore.count(_GITIGNORE_LINE) == 1

    constitution = (consumer / ".spaex" / "constitution.md").read_text(
        encoding="utf-8"
    )
    assert "hello-hook demo" in constitution

    lock = _read_lock(consumer)
    assert len(lock.molecules) == 1
    entry = lock.molecules[0]
    assert entry.id == _MOLECULE_ID
    assert entry.hook_status == "ok"


# --- T020 AS2 -------------------------------------------------------------


def test_hook_is_idempotent_on_second_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AS2: re-running install keeps the gitignore line once, hook_status stays ok."""
    canonical, head, state_root = _publish_hook_molecule(tmp_path)
    consumer = _make_consumer(tmp_path)

    assert (
        _run_add(consumer, state_root, monkeypatch, source_url=canonical, revision=head)
        == 0
    )

    # A second install re-runs the hook; script is idempotent so gitignore
    # stays at one line and hook_status remains "ok" in install.lock.
    assert _run_install(consumer, state_root, monkeypatch) == 0

    gitignore = (consumer / ".gitignore").read_text(encoding="utf-8")
    assert gitignore.count(_GITIGNORE_LINE) == 1

    lock = _read_lock(consumer)
    assert lock.molecules[0].hook_status == "ok"


# --- T021 AS3 (PTY prompt) ------------------------------------------------


_INTERACTIVE_HOOK = '''#!/usr/bin/env python3
from pathlib import Path
import sys

answer = input("proceed? ")
Path.cwd().joinpath(".hook-prompt-answer").write_text(answer, encoding="utf-8")
sys.exit(0)
'''


@pytest.mark.skipif(sys.platform.startswith("win"), reason="pty is Unix-only")
def test_hook_interactive_prompt_via_pty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AS3: hook prompt reaches operator via inherited stdio in a real PTY."""
    import pty
    import selectors

    canonical, head, state_root = _publish_hook_molecule(
        tmp_path, hook_body=_INTERACTIVE_HOOK
    )
    consumer = _make_consumer(tmp_path)

    # Locate the in-tree src/ so the subprocess loads the same package the
    # in-process tests do (installed copies may lag behind editable src).
    src_dir = Path(__file__).resolve().parents[2] / "src"

    parent_fd, child_fd = pty.openpty()
    pid = os.fork()
    if pid == 0:
        # child: attach the pty to stdio and exec spaex add.
        os.close(parent_fd)
        os.setsid()
        os.dup2(child_fd, 0)
        os.dup2(child_fd, 1)
        os.dup2(child_fd, 2)
        os.close(child_fd)
        os.environ["SPAEX_STATE"] = str(state_root)
        existing = os.environ.get("PYTHONPATH", "")
        os.environ["PYTHONPATH"] = (
            f"{src_dir}{os.pathsep}{existing}" if existing else str(src_dir)
        )
        os.execvp(
            sys.executable,
            [
                sys.executable,
                "-m",
                "spaex",
                "--repo-root",
                str(consumer),
                "add",
                canonical,
                _MOLECULE_ID,
                "--revision",
                head,
                "--lock-timeout",
                "5",
            ],
        )
    os.close(child_fd)
    # parent: read until we see the prompt, then write the answer.
    sel = selectors.DefaultSelector()
    sel.register(parent_fd, selectors.EVENT_READ)
    buf = b""
    saw_prompt = False
    deadline_ticks = 300  # ~30 seconds at 0.1s poll interval
    while deadline_ticks > 0:
        events = sel.select(timeout=0.1)
        if not events:
            deadline_ticks -= 1
            continue
        try:
            chunk = os.read(parent_fd, 4096)
        except OSError:
            # On Linux, the parent-side read raises EIO once the child
            # closes the slave fd. Treat as EOF.
            break
        if not chunk:
            break
        buf += chunk
        if not saw_prompt and b"proceed?" in buf:
            saw_prompt = True
            os.write(parent_fd, b"yes\n")
        # process may exit; loop reads until EOF.
    _, status = os.waitpid(pid, 0)
    os.close(parent_fd)

    assert saw_prompt, f"prompt never appeared; captured:\n{buf.decode(errors='replace')}"
    exit_code = os.waitstatus_to_exitcode(status)
    assert exit_code == 0, f"spaex exit code {exit_code}; captured:\n{buf.decode(errors='replace')}"

    answer_file = consumer / ".hook-prompt-answer"
    assert answer_file.exists()
    assert answer_file.read_text(encoding="utf-8").strip() == "yes"


# --- T022 edge case (EOFError fallback in non-TTY env) --------------------


_EOFERROR_FALLBACK_HOOK = '''#!/usr/bin/env python3
"""Hook expects operator input but tolerates a non-TTY environment (Spec 016)."""
from pathlib import Path
import sys

try:
    answer = input("proceed? ")
except EOFError:
    answer = "yes-default"

Path.cwd().joinpath(".hook-eoferror-answer").write_text(answer, encoding="utf-8")
sys.exit(0)
'''


def test_hook_eoferror_in_non_tty_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T022: stdin piped from /dev/null; hook catches EOFError, install still succeeds."""
    canonical, head, state_root = _publish_hook_molecule(
        tmp_path, hook_body=_EOFERROR_FALLBACK_HOOK
    )
    consumer = _make_consumer(tmp_path)

    devnull = open(os.devnull, "rb")
    try:
        monkeypatch.setattr("sys.stdin", devnull)
        rc = _run_add(
            consumer,
            state_root,
            monkeypatch,
            source_url=canonical,
            revision=head,
        )
    finally:
        devnull.close()
    assert rc == 0

    answer_file = consumer / ".hook-eoferror-answer"
    assert answer_file.exists()
    assert answer_file.read_text(encoding="utf-8").strip() == "yes-default"

    lock = _read_lock(consumer)
    assert lock.molecules[0].hook_status == "ok"
