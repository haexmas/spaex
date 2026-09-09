"""T014 - hook_runner unit tests + real-store containment regression (Spec 016)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from spaex.constitution.resolve import ResolvedMolecule
from spaex.git import molecule_store
from spaex.install import hook_runner
from spaex.install.hook_runner import HookOutcome, HookOutcomeKind, run_install_hook
from spaex.migrate.transform import clone_dir
from spaex.model.molecule_manifest import InstallHook
from spaex.util.errors import MoleculeTreeExtractionError, MoleculeTreePathNotFoundError

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary required"
)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "haex-test@example.com")
    _git(root, "config", "user.name", "haex-test")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "config", "core.autocrlf", "false")


def _make_resolved(
    tmp_path: Path,
    *,
    script: str = "install.py",
    args: tuple[str, ...] = (),
    on_failure: str = "warn",
    interpreter: str = "python3",
) -> ResolvedMolecule:
    return ResolvedMolecule(
        molecule_id="com.example.publisher.mol",
        source_url="https://example.invalid/example/publisher",
        revision="0" * 40,
        repo_dir=tmp_path / "clone",
        molecule_path="mol",
        install_hook=InstallHook(
            interpreter=interpreter,
            script=script,
            args=args,
            on_failure=on_failure,  # type: ignore[arg-type]
        ),
        effective_priority=10,
    )


@dataclass
class _StoreRecorder:
    """Records the (repo_dir, source_url, revision, molecule_path, state_root)."""

    call_args: tuple | None = None

    def __call__(
        self,
        repo_dir: Path,
        source_url: str,
        revision: str,
        molecule_path: str,
        state_root: Path,
    ) -> Path:
        self.call_args = (repo_dir, source_url, revision, molecule_path, state_root)
        target = state_root / "extracted" / molecule_path
        target.mkdir(parents=True, exist_ok=True)
        (target / "install.py").write_text("#!/usr/bin/env python3\n")
        return target


@dataclass
class _SubprocessRecorder:
    """Records subprocess.run() arguments and returns a canned CompletedProcess."""

    returncode: int = 0
    raise_: Exception | None = None
    call_kwargs: dict | None = None

    def __call__(self, argv: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.call_kwargs = {"argv": argv, **kwargs}
        if self.raise_ is not None:
            raise self.raise_
        return subprocess.CompletedProcess(args=argv, returncode=self.returncode)


def test_zero_exit_returns_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    resolved = _make_resolved(tmp_path)
    monkeypatch.setattr(hook_runner.shutil, "which", lambda name: "/usr/bin/" + name)
    store = _StoreRecorder()
    monkeypatch.setattr(hook_runner.molecule_store, "get_or_extract", store)
    subp = _SubprocessRecorder(returncode=0)
    monkeypatch.setattr(hook_runner.subprocess, "run", subp)

    outcome = run_install_hook(resolved, tmp_path / "consumer", tmp_path / "state")

    assert outcome == HookOutcome(kind=HookOutcomeKind.OK)


def test_nonzero_exit_returns_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resolved = _make_resolved(tmp_path)
    monkeypatch.setattr(hook_runner.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(hook_runner.molecule_store, "get_or_extract", _StoreRecorder())
    monkeypatch.setattr(hook_runner.subprocess, "run", _SubprocessRecorder(returncode=7))

    outcome = run_install_hook(resolved, tmp_path / "consumer", tmp_path / "state")

    assert outcome.kind is HookOutcomeKind.NONZERO_EXIT
    assert outcome.exit_code == 7


def test_argv_uses_canonical_target_cwd_and_no_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resolved = _make_resolved(tmp_path, args=("--verbose",))
    monkeypatch.setattr(hook_runner.shutil, "which", lambda name: "/usr/bin/" + name)
    store = _StoreRecorder()
    monkeypatch.setattr(hook_runner.molecule_store, "get_or_extract", store)
    subp = _SubprocessRecorder(returncode=0)
    monkeypatch.setattr(hook_runner.subprocess, "run", subp)

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    state = tmp_path / "state"
    run_install_hook(resolved, consumer, state)

    assert subp.call_kwargs is not None
    assert subp.call_kwargs["cwd"] == consumer
    assert "env" not in subp.call_kwargs
    assert "capture_output" not in subp.call_kwargs
    assert "stdin" not in subp.call_kwargs
    assert subp.call_kwargs["check"] is False

    argv = subp.call_kwargs["argv"]
    assert argv[0] == "python3"
    canonical = (state / "extracted" / "mol" / "install.py").resolve(strict=True)
    assert Path(argv[1]) == canonical
    assert argv[2:] == ["--verbose"]


def test_store_is_called_with_record_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resolved = _make_resolved(tmp_path)
    monkeypatch.setattr(hook_runner.shutil, "which", lambda name: "/usr/bin/" + name)
    store = _StoreRecorder()
    monkeypatch.setattr(hook_runner.molecule_store, "get_or_extract", store)
    monkeypatch.setattr(hook_runner.subprocess, "run", _SubprocessRecorder(returncode=0))

    run_install_hook(resolved, tmp_path / "consumer", tmp_path / "state")

    assert store.call_args == (
        resolved.repo_dir,
        resolved.source_url,
        resolved.revision,
        resolved.molecule_path,
        tmp_path / "state",
    )


def test_missing_interpreter_does_not_call_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resolved = _make_resolved(tmp_path, interpreter="nonexistent-xyz")
    monkeypatch.setattr(hook_runner.shutil, "which", lambda name: None)
    store = _StoreRecorder()
    monkeypatch.setattr(hook_runner.molecule_store, "get_or_extract", store)
    subp = _SubprocessRecorder()
    monkeypatch.setattr(hook_runner.subprocess, "run", subp)

    outcome = run_install_hook(resolved, tmp_path / "consumer", tmp_path / "state")

    assert outcome.kind is HookOutcomeKind.LAUNCH_FAILURE
    assert outcome.reason == "interpreter_not_on_path"
    assert store.call_args is None
    assert subp.call_kwargs is None


@pytest.mark.parametrize(
    "raised",
    [
        MoleculeTreePathNotFoundError(message="not found"),
        MoleculeTreeExtractionError(message="bad archive"),
    ],
)
def test_store_error_maps_to_molecule_tree_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raised: Exception
) -> None:
    resolved = _make_resolved(tmp_path)
    monkeypatch.setattr(hook_runner.shutil, "which", lambda name: "/usr/bin/" + name)

    def _raise(*args, **kwargs):
        raise raised

    monkeypatch.setattr(hook_runner.molecule_store, "get_or_extract", _raise)
    subp = _SubprocessRecorder()
    monkeypatch.setattr(hook_runner.subprocess, "run", subp)

    outcome = run_install_hook(resolved, tmp_path / "consumer", tmp_path / "state")

    assert outcome.kind is HookOutcomeKind.LAUNCH_FAILURE
    assert outcome.reason == "molecule_tree_unavailable"
    assert subp.call_kwargs is None


@pytest.mark.skipif(sys.platform.startswith("win"), reason="symlink-based test")
def test_broken_symlink_returns_path_containment_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resolved = _make_resolved(tmp_path)
    monkeypatch.setattr(hook_runner.shutil, "which", lambda name: "/usr/bin/" + name)

    def _stub_extract(*args, **kwargs) -> Path:
        molecule_dir = tmp_path / "state" / "mol"
        molecule_dir.mkdir(parents=True, exist_ok=True)
        os.symlink(molecule_dir / "does-not-exist", molecule_dir / "install.py")
        return molecule_dir

    monkeypatch.setattr(hook_runner.molecule_store, "get_or_extract", _stub_extract)
    subp = _SubprocessRecorder()
    monkeypatch.setattr(hook_runner.subprocess, "run", subp)

    outcome = run_install_hook(resolved, tmp_path / "consumer", tmp_path / "state")

    assert outcome.kind is HookOutcomeKind.LAUNCH_FAILURE
    assert outcome.reason == "path_containment_failure"
    assert subp.call_kwargs is None


@pytest.mark.skipif(sys.platform.startswith("win"), reason="symlink-based test")
def test_internal_symlink_is_ok_with_canonical_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resolved = _make_resolved(tmp_path, script="hop.py")
    monkeypatch.setattr(hook_runner.shutil, "which", lambda name: "/usr/bin/" + name)

    def _stub_extract(*args, **kwargs) -> Path:
        molecule_dir = tmp_path / "state" / "mol"
        molecule_dir.mkdir(parents=True, exist_ok=True)
        real = molecule_dir / "real.py"
        real.write_text("ok\n")
        os.symlink(real, molecule_dir / "hop.py")
        return molecule_dir

    monkeypatch.setattr(hook_runner.molecule_store, "get_or_extract", _stub_extract)
    subp = _SubprocessRecorder(returncode=0)
    monkeypatch.setattr(hook_runner.subprocess, "run", subp)

    outcome = run_install_hook(resolved, tmp_path / "consumer", tmp_path / "state")

    assert outcome.kind is HookOutcomeKind.OK
    argv = subp.call_kwargs["argv"]
    canonical = (tmp_path / "state" / "mol" / "real.py").resolve(strict=True)
    assert Path(argv[1]) == canonical


def test_process_launch_oserror_returns_launch_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resolved = _make_resolved(tmp_path)
    monkeypatch.setattr(hook_runner.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(hook_runner.molecule_store, "get_or_extract", _StoreRecorder())
    monkeypatch.setattr(
        hook_runner.subprocess,
        "run",
        _SubprocessRecorder(raise_=OSError("cannot exec")),
    )

    outcome = run_install_hook(resolved, tmp_path / "consumer", tmp_path / "state")

    assert outcome.kind is HookOutcomeKind.LAUNCH_FAILURE
    assert outcome.reason == "process_launch_oserror"


def test_keyboard_interrupt_returns_interrupted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resolved = _make_resolved(tmp_path)
    monkeypatch.setattr(hook_runner.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(hook_runner.molecule_store, "get_or_extract", _StoreRecorder())
    monkeypatch.setattr(
        hook_runner.subprocess,
        "run",
        _SubprocessRecorder(raise_=KeyboardInterrupt()),
    )

    outcome = run_install_hook(resolved, tmp_path / "consumer", tmp_path / "state")

    assert outcome.kind is HookOutcomeKind.INTERRUPTED
    assert outcome.reason == "interrupted"


# --- Real-store regression: sibling escape (T014 defense in depth) -------------


def _publish_sibling_escape_repo(publisher: Path) -> str:
    """Create a repo with mol/install.py -> ../sibling/install.py and sibling/install.py.

    Both files land in the repository. Spec 017's extraction of mol/ preserves
    the relative symlink; the hook_runner's execution-time containment check
    then catches the escape both immediately after extraction (sibling not yet
    materialized: broken symlink) and after the sibling has been materialized
    (target resolves outside the returned molecule directory).
    """
    publisher.mkdir(parents=True, exist_ok=True)
    _init_repo(publisher)
    mol_dir = publisher / "mol"
    sibling_dir = publisher / "sibling"
    mol_dir.mkdir()
    sibling_dir.mkdir()
    (sibling_dir / "install.py").write_text("#!/usr/bin/env python3\nprint('sibling')\n")
    os.symlink(Path("..") / "sibling" / "install.py", mol_dir / "install.py")
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-q", "-m", "sibling escape scenario")
    return _git(publisher, "rev-parse", "HEAD")


def _clone(state_root: Path, canonical: str, publisher: Path) -> Path:
    target = clone_dir(state_root, canonical)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(publisher, target)
    return target


@pytest.mark.skipif(sys.platform.startswith("win"), reason="symlink-based test")
def test_real_store_sibling_escape_refused_fresh_and_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """T014 real-store regression.

    Confirms the runner refuses a sibling-directory escape on both a fresh
    extraction (broken symlink resolves nowhere) and a cache hit after the
    sibling has been separately materialized (symlink resolves outside the
    returned molecule directory).
    """
    canonical = "https://example.invalid/example/publisher"
    publisher = tmp_path / "publisher"
    sha = _publish_sibling_escape_repo(publisher)
    state_root = tmp_path / "state"
    repo_dir = _clone(state_root, canonical, publisher)
    consumer = tmp_path / "consumer"
    consumer.mkdir()

    resolved = ResolvedMolecule(
        molecule_id="com.example.publisher.mol",
        source_url=canonical,
        revision=sha.lower(),
        repo_dir=repo_dir,
        molecule_path="mol",
        install_hook=InstallHook(
            interpreter="python3",
            script="install.py",
            args=(),
            on_failure="warn",
        ),
        effective_priority=10,
    )

    subp = _SubprocessRecorder()
    # Rebind hook_runner.subprocess only (not the shared subprocess module) so
    # Spec 017's git-archive subprocess.run keeps hitting the real binary.
    monkeypatch.setattr(hook_runner, "subprocess", SimpleNamespace(run=subp))

    first = run_install_hook(resolved, consumer, state_root)
    assert first.kind is HookOutcomeKind.LAUNCH_FAILURE
    assert first.reason == "path_containment_failure"
    assert subp.call_kwargs is None

    molecule_store.get_or_extract(repo_dir, canonical, sha.lower(), "sibling", state_root)

    second = run_install_hook(resolved, consumer, state_root)
    assert second.kind is HookOutcomeKind.LAUNCH_FAILURE
    assert second.reason == "path_containment_failure"
    assert subp.call_kwargs is None
