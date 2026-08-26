"""Two people pressing the same button must not corrupt the record.

Measured before the fix, not imagined: four concurrent closes of one period, and
one of them came back

    JournalTampered: decisions.jsonl: seq 0 at position 1 — an event is missing or moved

which is the most alarming message this system can produce. The log was fine.
`Journal(fresh=True)` unlinks the file and rewrites it, so two closes interleaved
and a reader caught the middle of one. Before the surfaces existed only the
benchmark ran a close, one process at a time, and nothing could collide.

The lock is `flock` on a sidecar — sidecar because the writer *deletes* the log,
and a lock held on a deleted inode protects nothing. Advisory, and honestly so:
it coordinates processes that ask. Everything in this repo asks; it is not a
substitute for the durable store this build does not have.

Threads and processes both, because they fail differently: threads share a
process and would pass a naive in-process mutex, and separate processes are what
a real deployment runs.
"""

from __future__ import annotations

import concurrent.futures as cf
import subprocess
import sys
import time
from pathlib import Path

import pytest

from recon import loop as looplib
from recon import service
from recon.journal import JournalBusy, exclusive, shared

LOOP = "settlement_3way"
BATCH = "A"


def test_concurrent_closes_in_one_process_agree(tmp_path: Path):
    def go(_: int) -> str:
        try:
            return service.close(LOOP, BATCH, runs_dir=tmp_path).run_id
        except Exception as exc:  # every failure mode is the finding
            return f"{type(exc).__name__}: {exc}"

    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(go, range(8)))

    assert len(set(results)) == 1, f"eight closes, {len(set(results))} outcomes: {set(results)}"
    assert not results[0].startswith(("Journal", "Service")), results[0]


def test_concurrent_closes_in_separate_processes_agree(tmp_path: Path):
    """The case a deployment actually has: uvicorn workers, not threads."""
    script = (
        "from pathlib import Path; from recon import service; "
        f"print(service.close({LOOP!r}, {BATCH!r}, runs_dir=Path({str(tmp_path)!r})).run_id)"
    )

    def go(_: int) -> str:
        done = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, cwd=Path.cwd()
        )
        return done.stdout.strip() if done.returncode == 0 else f"FAIL {done.stderr[-160:]}"

    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(go, range(6)))

    assert all(not r.startswith("FAIL") for r in results), [r for r in results if "FAIL" in r]
    assert len(set(results)) == 1, set(results)


def test_the_record_a_concurrent_close_leaves_is_readable(tmp_path: Path):
    """The symptom, checked at the place it was reported: the log must vouch for
    itself afterwards, and every close must have written a whole one."""
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: service.close(LOOP, BATCH, runs_dir=tmp_path), range(6)))

    run_id = service.stored_runs(tmp_path)[0]
    assert service.check_chain(service.events(run_id, tmp_path)).holds
    view = service.view(run_id, tmp_path)
    assert view.chain_problems == []
    assert view.complete and view.tiers.matched == 20


def test_a_reader_waits_for_a_writer_rather_than_seeing_half_a_log(tmp_path: Path):
    """The read side is where the bug was *visible*, so it gets its own lock.

    Constructed rather than raced: holding the exclusive lock and timing a
    shared acquire is deterministic, where a real race is a coin toss that
    passes on a fast machine and fails in CI.
    """
    log = tmp_path / "run" / "decisions.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("")

    released: list[float] = []

    def writer() -> None:
        with exclusive(log):
            time.sleep(0.25)
            released.append(time.monotonic())

    with cf.ThreadPoolExecutor(max_workers=2) as pool:
        held = pool.submit(writer)
        time.sleep(0.05)
        started = time.monotonic()
        with shared(log):
            acquired = time.monotonic()
        held.result()

    assert released, "the writer never ran"
    assert acquired >= released[0], "a reader got in while a writer held the log"
    assert acquired - started > 0.1, "the shared lock did not wait"


def test_the_service_read_path_takes_the_lock_not_just_the_primitive(tmp_path: Path):
    """The mutation that found this one deleted the lock from `service.events`
    and survived, because the test above exercises `shared()` directly.

    A lock nobody calls is a lock that is not there, and the caller who would
    have noticed is the one reading a close through the API while another
    process writes it. So this holds the writer's lock and times the *service*
    read — the path a request actually takes.
    """
    view = service.close(LOOP, BATCH, runs_dir=tmp_path)
    log = tmp_path / view.run_id / "decisions.jsonl"

    def hold() -> float:
        with exclusive(log):
            time.sleep(0.25)
            return time.monotonic()

    with cf.ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(hold)
        time.sleep(0.05)
        started = time.monotonic()
        stream = service.events(view.run_id, tmp_path)
        finished = time.monotonic()
        released = writer.result()

    assert stream, "the read returned nothing"
    assert finished >= released, "the service read a log while a writer held it"
    assert finished - started > 0.1, (
        "service.events did not wait for the writer — it is not taking the shared lock"
    )


def test_readers_do_not_block_each_other(tmp_path: Path):
    """A shared lock that behaved like an exclusive one would serialise every
    page view behind every other, which is a different bug with the same fix."""
    log = tmp_path / "run" / "decisions.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("")

    started = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=4) as pool:

        def read(_: int) -> None:
            with shared(log):
                time.sleep(0.15)

        list(pool.map(read, range(4)))
    assert time.monotonic() - started < 0.5, "four concurrent readers were serialised"


def test_a_stuck_writer_is_reported_rather_than_waited_on_forever(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A close takes milliseconds. Past the wait, the honest answer is that
    something is stuck — not a request that hangs until the client gives up and
    nobody learns why."""
    import recon.journal as journal

    monkeypatch.setattr(journal, "LOCK_WAIT_SECONDS", 0.2)
    log = tmp_path / "run" / "decisions.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("")

    def blocked() -> str:
        try:
            with exclusive(log):
                return "acquired"
        except JournalBusy as exc:
            return str(exc)

    with cf.ThreadPoolExecutor(max_workers=2) as pool, exclusive(log):
        outcome = pool.submit(blocked).result(timeout=5)

    assert "locked by another process" in outcome
    assert "stuck writer" in outcome


def test_the_lock_is_not_the_file_the_writer_deletes(tmp_path: Path):
    """`Journal(fresh=True)` unlinks the log. A lock on that inode is a lock on
    nothing once it is gone, and the next writer would take a fresh one on a new
    file while the first still believed it held something."""
    log = tmp_path / "run" / "decisions.jsonl"
    log.parent.mkdir(parents=True)
    with exclusive(log):
        assert (log.parent / f".{log.name}.lock").exists()
    assert not log.exists(), "the lock created the log it was supposed to guard"


def test_a_close_still_writes_a_whole_record_under_the_lock(tmp_path: Path):
    """The lock must not have changed what a close records."""
    view = service.close(LOOP, BATCH, runs_dir=tmp_path)
    reference = service.close(LOOP, BATCH, runs_dir=tmp_path / "again")
    assert view.run_id == reference.run_id
    assert view.tiers == reference.tiers
    assert view.events == reference.events
    assert looplib.RUNS  # untouched by this test


def test_the_lock_is_the_one_nfs_implements():
    """`flock` over NFS is emulated and the emulation is not dependable.

    This is not a style preference. Locally `flock` worked and every test in this
    file passed; on EFS the first close wrote its log and every read afterwards
    timed out at thirty seconds reporting "a stuck writer" about a writer that
    had finished. The whole reason this deployment is Fargate with a filesystem
    rather than something serverless was "NFSv4 supports that lock" — and the
    claim was about the wrong call.

    Asserted structurally because nothing in CI runs on NFS. The next person to
    reach for `flock` here will not have an EFS mount to find out on either.
    """
    import inspect

    from recon import journal

    source = inspect.getsource(journal._locked) + inspect.getsource(journal._take_file_lock)
    assert "fcntl.lockf" in source
    assert "fcntl.flock" not in source, (
        "flock is back. It works everywhere except the filesystem this is "
        "deployed on, which is the worst possible place for it to work."
    )


def test_a_reader_and_a_writer_in_one_process_do_not_deadlock(tmp_path):
    """`lockf` holds a POSIX record lock per *process*, so two threads here
    cannot block each other with it at all — the in-process half has to be a real
    lock or a writer and a reader would both proceed at once.

    The close runs on a background thread while requests are served on others,
    which is exactly this shape.
    """
    import threading

    from recon.journal import exclusive, shared

    log = tmp_path / "decisions.jsonl"
    log.write_text("")
    order, errors = [], []

    def writer():
        try:
            with exclusive(log):
                order.append("write-in")
                time.sleep(0.25)
                order.append("write-out")
        except Exception as exc:
            errors.append(exc)

    def reader():
        try:
            time.sleep(0.05)
            with shared(log):
                order.append("read")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert not errors, errors
    assert order == ["write-in", "write-out", "read"], (
        f"a reader overlapped a writer in one process: {order}"
    )
