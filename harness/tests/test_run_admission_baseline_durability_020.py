"""OpenSpec 020 D1.5: baseline artifacts are durable before settlement."""

from __future__ import annotations

import asyncio
import fcntl
import os
import shutil
import stat
from pathlib import Path

import pytest

from insurance_harness.compiler import pipeline

_ARTIFACT_NAMES = (
    "pred.jsonl",
    "judge-queue.jsonl",
    "dead-letters.jsonl",
    "manifest.json",
)


def _seed_old_commit(run_dir: Path) -> None:
    for name in _ARTIFACT_NAMES:
        (run_dir / name).write_text(f"old:{name}", encoding="utf-8")


def _assert_commit_cleared(run_dir: Path) -> None:
    assert not any((run_dir / name).exists() for name in _ARTIFACT_NAMES)


def test_d1_5_pipeline_precommit_rejection_installs_no_commit_marker(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    sentinel = RuntimeError("precommit rejected")
    observed: list[pipeline.RunArtifactCommitCandidate] = []

    def reject(candidate: pipeline.RunArtifactCommitCandidate) -> None:
        observed.append(candidate)
        raise sentinel

    with pytest.raises(RuntimeError) as caught:
        pipeline._commit_run_artifacts(
            run_dir=run_dir,
            pred_text='{"field_id":"waiting_period"}\n',
            manifest_text='{"run_id":"020-baseline"}',
            judge_requests=[],
            dead_letter_text="",
            precommit_validator=reject,
        )

    assert caught.value is sentinel
    assert len(observed) == 1
    assert observed[0].manifest == b'{"run_id":"020-baseline"}'
    _assert_commit_cleared(run_dir)


def test_d1_5_pipeline_precommit_rejection_preserves_existing_committed_run(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_old_commit(run_dir)
    expected = {name: (run_dir / name).read_bytes() for name in _ARTIFACT_NAMES}
    sentinel = RuntimeError("precommit rejected")

    def reject(_candidate: pipeline.RunArtifactCommitCandidate) -> None:
        raise sentinel

    with pytest.raises(RuntimeError) as caught:
        pipeline._commit_run_artifacts(
            run_dir=run_dir,
            pred_text='{"field_id":"waiting_period"}\n',
            manifest_text='{"run_id":"020-baseline"}',
            judge_requests=[],
            dead_letter_text="",
            precommit_validator=reject,
        )

    assert caught.value is sentinel
    assert {name: (run_dir / name).read_bytes() for name in _ARTIFACT_NAMES} == expected


def test_d1_5_pipeline_fsyncs_each_artifact_then_commits_manifest_and_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events: list[tuple[str, int, str]] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def tracked_fsync(descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        kind = "directory" if stat.S_ISDIR(metadata.st_mode) else "file"
        events.append(("fsync", metadata.st_ino, kind))
        real_fsync(descriptor)

    def tracked_replace(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        inode = source_path.stat().st_ino
        events.append(("replace", inode, destination_path.name))
        real_replace(source_path, destination_path)

    monkeypatch.setattr(os, "fsync", tracked_fsync)
    monkeypatch.setattr(os, "replace", tracked_replace)

    pipeline._commit_run_artifacts(
        run_dir=run_dir,
        pred_text='{"field_id":"waiting_period"}\n',
        manifest_text='{"run_id":"020-baseline"}',
        judge_requests=[],
        dead_letter_text="",
    )

    replace_events = [event for event in events if event[0] == "replace"]
    assert [event[2] for event in replace_events] == [
        "pred.jsonl",
        "judge-queue.jsonl",
        "dead-letters.jsonl",
        "manifest.json",
    ]
    for replace_event in replace_events:
        replace_index = events.index(replace_event)
        assert any(
            event[0] == "fsync"
            and event[1] == replace_event[1]
            and event[2] == "file"
            for event in events[:replace_index]
        ), f"{replace_event[2]} was replaced before its exact content inode was fsynced"

    manifest_replace_index = events.index(replace_events[-1])
    run_dir_inode = run_dir.stat().st_ino
    assert any(
        event == ("fsync", run_dir_inode, "directory")
        for event in events[manifest_replace_index + 1 :]
    ), "run directory must be fsynced after manifest is installed last"


def test_d1_5_pipeline_reads_back_manifest_commit_marker_before_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    real_replace = os.replace

    def corrupt_manifest_after_replace(
        source: str | Path,
        destination: str | Path,
    ) -> None:
        destination_path = Path(destination)
        real_replace(source, destination_path)
        if destination_path.name == "manifest.json":
            destination_path.write_text('{"run_id":"corrupted"}', encoding="utf-8")

    monkeypatch.setattr(os, "replace", corrupt_manifest_after_replace)

    with pytest.raises(RuntimeError, match="manifest.*read-back") as caught:
        pipeline._commit_run_artifacts(
            run_dir=run_dir,
            pred_text='{"field_id":"waiting_period"}\n',
            manifest_text='{"run_id":"020-baseline"}',
            judge_requests=[],
            dead_letter_text="",
        )

    _assert_commit_cleared(run_dir)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert str(tmp_path) not in str(caught.value)
    assert "020-baseline" not in str(caught.value)


def test_d1_5_pipeline_staging_cleanup_failure_cannot_report_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    def fail_unless_ignored(
        _path: str | Path,
        *,
        ignore_errors: bool = False,
    ) -> None:
        if ignore_errors:
            return
        raise OSError("private injected staging cleanup details")

    monkeypatch.setattr(shutil, "rmtree", fail_unless_ignored)

    with pytest.raises(RuntimeError, match="^run artifact staging cleanup failed$"):
        pipeline._commit_run_artifacts(
            run_dir=run_dir,
            pred_text='{"field_id":"waiting_period"}\n',
            manifest_text='{"run_id":"020-baseline"}',
            judge_requests=[],
            dead_letter_text="",
        )


def test_d1_5_pipeline_fsyncs_run_directory_after_staging_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_dir_inode = run_dir.stat().st_ino
    events: list[str] = []
    real_fsync = os.fsync
    real_rmtree = shutil.rmtree

    def tracked_fsync(descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        if stat.S_ISDIR(metadata.st_mode) and metadata.st_ino == run_dir_inode:
            events.append("fsync-run-dir")
        real_fsync(descriptor)

    def tracked_rmtree(
        path: str | Path,
        *,
        ignore_errors: bool = False,
    ) -> None:
        events.append("remove-staging")
        real_rmtree(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(os, "fsync", tracked_fsync)
    monkeypatch.setattr(shutil, "rmtree", tracked_rmtree)

    pipeline._commit_run_artifacts(
        run_dir=run_dir,
        pred_text='{"field_id":"waiting_period"}\n',
        manifest_text='{"run_id":"020-baseline"}',
        judge_requests=[],
        dead_letter_text="",
    )

    cleanup_index = events.index("remove-staging")
    assert "fsync-run-dir" in events[cleanup_index + 1 :]


def test_d1_5_pipeline_durably_removes_old_manifest_before_old_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_old_commit(run_dir)
    events: list[tuple[str, str]] = []
    real_fsync = os.fsync
    real_replace = os.replace
    real_unlink = Path.unlink

    def tracked_fsync(descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        if stat.S_ISDIR(metadata.st_mode):
            events.append(("fsync", "run-dir"))
        real_fsync(descriptor)

    def tracked_replace(source: str | Path, destination: str | Path) -> None:
        events.append(("replace", Path(destination).name))
        real_replace(source, destination)

    def tracked_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.parent == run_dir and self.name in _ARTIFACT_NAMES:
            events.append(("unlink", self.name))
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(os, "fsync", tracked_fsync)
    monkeypatch.setattr(os, "replace", tracked_replace)
    monkeypatch.setattr(Path, "unlink", tracked_unlink)

    pipeline._commit_run_artifacts(
        run_dir=run_dir,
        pred_text='{"field_id":"waiting_period"}\n',
        manifest_text='{"run_id":"020-baseline"}',
        judge_requests=[],
        dead_letter_text="",
    )

    first_replace = next(index for index, event in enumerate(events) if event[0] == "replace")
    assert events[:first_replace] == [
        ("unlink", "manifest.json"),
        ("fsync", "run-dir"),
        ("unlink", "pred.jsonl"),
        ("unlink", "judge-queue.jsonl"),
        ("unlink", "dead-letters.jsonl"),
        ("fsync", "run-dir"),
    ]


@pytest.mark.parametrize(
    "failure_phase",
    [
        "staged-file-fsync",
        "old-manifest-removal-fsync",
        "old-data-removal-fsync",
        "data-replace",
        "manifest-replace",
        "commit-directory-fsync",
        "manifest-readback",
    ],
)
def test_d1_5_pipeline_io_failure_matrix_clears_all_commit_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_old_commit(run_dir)
    old_commit = {name: (run_dir / name).read_bytes() for name in _ARTIFACT_NAMES}
    real_fsync = os.fsync
    real_replace = os.replace
    real_read_bytes = Path.read_bytes
    directory_fsync_count = 0
    injected = False

    def fail_selected_fsync(descriptor: int) -> None:
        nonlocal directory_fsync_count, injected
        metadata = os.fstat(descriptor)
        is_directory = stat.S_ISDIR(metadata.st_mode)
        if is_directory:
            directory_fsync_count += 1
        phase_matches = (
            failure_phase == "staged-file-fsync" and not is_directory
        ) or (
            failure_phase == "old-manifest-removal-fsync"
            and is_directory
            and directory_fsync_count == 1
        ) or (
            failure_phase == "old-data-removal-fsync"
            and is_directory
            and directory_fsync_count == 2
        ) or (
            failure_phase == "commit-directory-fsync"
            and is_directory
            and directory_fsync_count == 3
        )
        if phase_matches and not injected:
            injected = True
            raise OSError("private injected fsync details")
        real_fsync(descriptor)

    def fail_selected_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal injected
        destination_name = Path(destination).name
        phase_matches = (
            failure_phase == "data-replace"
            and destination_name == "judge-queue.jsonl"
        ) or (
            failure_phase == "manifest-replace"
            and destination_name == "manifest.json"
        )
        if phase_matches and not injected:
            injected = True
            raise OSError("private injected replace details")
        real_replace(source, destination)

    def fail_selected_readback(self: Path) -> bytes:
        nonlocal injected
        if (
            failure_phase == "manifest-readback"
            and self == run_dir / "manifest.json"
            and not injected
        ):
            injected = True
            raise OSError("private injected readback details")
        return real_read_bytes(self)

    monkeypatch.setattr(os, "fsync", fail_selected_fsync)
    monkeypatch.setattr(os, "replace", fail_selected_replace)
    monkeypatch.setattr(Path, "read_bytes", fail_selected_readback)

    expected_message = (
        "run artifact manifest read-back failed"
        if failure_phase == "manifest-readback"
        else "run artifact commit failed"
    )
    with pytest.raises(RuntimeError, match=f"^{expected_message}$") as caught:
        pipeline._commit_run_artifacts(
            run_dir=run_dir,
            pred_text='{"field_id":"waiting_period"}\n',
            manifest_text='{"run_id":"020-baseline"}',
            judge_requests=[],
            dead_letter_text="",
        )

    assert injected is True
    if failure_phase == "staged-file-fsync":
        assert {
            name: (run_dir / name).read_bytes() for name in _ARTIFACT_NAMES
        } == old_commit
    else:
        _assert_commit_cleared(run_dir)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "private injected" not in str(caught.value)
    assert str(tmp_path) not in str(caught.value)


@pytest.mark.parametrize(
    "error_type",
    [asyncio.CancelledError, KeyboardInterrupt, SystemExit],
)
def test_d1_5_pipeline_cleans_up_then_reraises_control_flow_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_old_commit(run_dir)
    real_replace = os.replace
    injected_error = error_type("control-flow sentinel")
    injected = False

    def interrupt_manifest_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal injected
        if Path(destination).name == "manifest.json" and not injected:
            injected = True
            raise injected_error
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", interrupt_manifest_replace)

    with pytest.raises(error_type) as caught:
        pipeline._commit_run_artifacts(
            run_dir=run_dir,
            pred_text='{"field_id":"waiting_period"}\n',
            manifest_text='{"run_id":"020-baseline"}',
            judge_requests=[],
            dead_letter_text="",
        )

    assert caught.value is injected_error
    _assert_commit_cleared(run_dir)


@pytest.mark.asyncio
async def test_d1_5_pipeline_opens_private_run_lock_relative_to_verified_run_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    lock_opens: list[tuple[int, int | None]] = []
    real_open = os.open

    def tracked_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if os.fsdecode(path) == ".run.lock":
            lock_opens.append((flags, dir_fd))
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", tracked_open)

    async with pipeline._exclusive_run_directory(run_dir):
        assert lock_opens

    required = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
    assert all(flags & required == required for flags, _ in lock_opens)
    assert all(directory_fd is not None for _, directory_fd in lock_opens)
    metadata = (run_dir / ".run.lock").stat(follow_symlinks=False)
    assert stat.S_ISREG(metadata.st_mode)
    assert metadata.st_uid == os.geteuid()
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert metadata.st_nlink == 1


@pytest.mark.asyncio
async def test_d1_5_settlement_guard_blocks_another_run_writer_until_settle_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    competing_writer_blocked = asyncio.Event()
    competing_writer_entered = asyncio.Event()
    real_flock = fcntl.flock

    def observed_flock(file_descriptor: int, operation: int) -> None:
        try:
            real_flock(file_descriptor, operation)
        except BlockingIOError:
            competing_writer_blocked.set()
            raise

    monkeypatch.setattr(fcntl, "flock", observed_flock)

    async def competing_writer() -> None:
        async with pipeline._exclusive_run_directory(run_dir):
            competing_writer_entered.set()

    async with pipeline.run_settlement_guard(run_dir):
        writer_task = asyncio.create_task(competing_writer())
        await asyncio.wait_for(competing_writer_blocked.wait(), timeout=1)
        assert not competing_writer_entered.is_set()

    await asyncio.wait_for(writer_task, timeout=1)
    assert competing_writer_entered.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_kind",
    ["symlink", "directory", "hardlink", "public-mode"],
)
async def test_d1_5_pipeline_rejects_unsafe_preexisting_run_lock(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    lock_path = run_dir / ".run.lock"
    outside = tmp_path / "outside-lock"
    if unsafe_kind == "symlink":
        outside.write_bytes(b"outside")
        outside.chmod(0o644)
        lock_path.symlink_to(outside)
    elif unsafe_kind == "directory":
        lock_path.mkdir(mode=0o700)
    elif unsafe_kind == "hardlink":
        outside.write_bytes(b"outside")
        outside.chmod(0o600)
        os.link(outside, lock_path)
    else:
        lock_path.write_bytes(b"lock")
        lock_path.chmod(0o644)

    with pytest.raises(RuntimeError, match="^run directory lock is unsafe$"):
        async with pipeline._exclusive_run_directory(run_dir):
            pytest.fail("unsafe run lock was acquired", pytrace=False)

    if unsafe_kind in {"symlink", "public-mode"}:
        protected = outside if unsafe_kind == "symlink" else lock_path
        assert stat.S_IMODE(protected.stat().st_mode) == 0o644
