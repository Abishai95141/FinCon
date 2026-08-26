"""What a close is doing while it does it.

A close takes a couple of seconds, and for those seconds the old surface showed
nothing at all — the request hung and then a finished page appeared. That is
survivable and it is also the moment a controller most wants to know what the
machine is doing with their books.

**The stages are the real ones.** `ingest · block · match · verify · post ·
record` are the pipeline's actual boundaries, and each reports the fact it
produced — "543 rows, 5 intake checks passed", "20 matched", "20/20 re-derived".
A progress bar that interpolated between them would be an animation, and an
animation of work is not a report of work.

**Timing lives here and nowhere else.** CLAUDE.md bans a wall clock inside a
decision: the same close must record the same thing twice running, so elapsed
milliseconds stay in this file and never reach the decision log.

The store is one JSON file per job, written whole and renamed into place, so a
reader polling it sees either the previous state or the next one and never half
of either.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: The pipeline, named once. The surface renders this list before anything has
#: happened, so a reader sees the whole shape of the work up front rather than
#: watching steps appear one at a time from nowhere.
STAGES: tuple[tuple[str, str], ...] = (
    ("ingest", "Read both sources and prove them"),
    ("block", "Narrow the pairs worth comparing"),
    ("match", "Run the loop's strategies in order"),
    ("verify", "Re-derive every match from raw records"),
    ("post", "Write the journal and assert the balance"),
    ("record", "Derive the decision log and seal it"),
)
STAGE_NAMES = tuple(name for name, _ in STAGES)


@dataclass
class Stage:
    name: str
    state: str = "waiting"
    """`waiting` | `running` | `done` | `failed`. Four states rather than a
    percentage, because the work is discrete and a percentage would be invented."""

    detail: str = ""
    elapsed_ms: int = 0


@dataclass
class Job:
    job_id: str
    loop: str
    source_set: str
    state: str = "running"
    run_id: str = ""
    error: str = ""
    stages: list[Stage] = field(default_factory=lambda: [Stage(n) for n in STAGE_NAMES])

    @property
    def done(self) -> bool:
        return self.state in {"complete", "failed"}

    def stage(self, name: str) -> Stage:
        for stage in self.stages:
            if stage.name == name:
                return stage
        raise KeyError(f"{name!r} is not a pipeline stage; known: {STAGE_NAMES}")


class Tracker:
    """Records stage transitions for one close, for someone else to read.

    Deliberately tolerant of a stage nobody reports: a pipeline that grows a
    seventh step should not crash a page, it should show six done and one
    unaccounted for. `finish()` marks any stage still waiting as such, so a run
    that ended early is visible as an incomplete pipeline rather than as a
    pipeline that never started those steps.
    """

    def __init__(self, root: Path, loop: str, source_set: str, job_id: str | None = None):
        self.root = root
        self.job = Job(job_id or uuid.uuid4().hex[:12], loop, source_set)
        self._started = time.monotonic()
        self._stage_started = self._started
        self._current: str | None = None
        self.write()

    @property
    def path(self) -> Path:
        return self.root / f"{self.job.job_id}.json"

    def write(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        # Whole file, then rename. A reader polling every second must see the
        # previous state or the next one, never half of either.
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self.job), indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def enter(self, name: str, detail: str = "") -> None:
        now = time.monotonic()
        if self._current:
            previous = self.job.stage(self._current)
            if previous.state == "running":
                previous.state = "done"
                previous.elapsed_ms = int((now - self._stage_started) * 1000)
        stage = self.job.stage(name)
        stage.state, stage.detail = "running", detail
        self._current, self._stage_started = name, now
        self.write()

    def report(self, name: str, detail: str) -> None:
        """Attach the fact a stage produced. Called as the stage *ends*, because
        the interesting number — 543 rows, 20 matched — does not exist until
        then, and a stage announcing a total before it has one would be
        inventing it."""
        stage = self.job.stage(name)
        stage.detail = detail
        self.write()

    def finish(self, run_id: str) -> None:
        now = time.monotonic()
        if self._current:
            last = self.job.stage(self._current)
            last.state = "done"
            last.elapsed_ms = int((now - self._stage_started) * 1000)
        self.job.state, self.job.run_id = "complete", run_id
        self.write()

    def fail(self, error: str) -> None:
        """A close that died mid-stage. The stage it died in says so, and the
        rest stay `waiting` rather than being marked done — a failure that
        painted the remaining steps green would be the worst possible lie for
        this product to tell."""
        if self._current:
            self.job.stage(self._current).state = "failed"
        self.job.state, self.job.error = "failed", error
        self.write()


def read(root: Path, job_id: str) -> Job | None:
    path = root / f"{job_id}.json"
    if not path.exists():
        return None
    body = json.loads(path.read_text(encoding="utf-8"))
    body["stages"] = [Stage(**stage) for stage in body.get("stages", [])]
    return Job(**body)
