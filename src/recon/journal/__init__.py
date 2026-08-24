"""The append-only decision log.

A file cannot be made append-only by asking nicely, so this does the next
honest thing: every event carries the hash of the one before it, and the hash
covers its own content. An edit, a deletion or a reorder breaks the chain and
`verify_chain` says where.

**What this does not defend against, stated plainly:** an actor who can rewrite
the whole file can recompute the chain over anything they like. A chain proves
internal consistency, not custody. Real custody needs an external anchor — a
WORM store, a countersignature, or a digest published somewhere we do not
control — and none of those exist here. The chain is worth having because the
realistic failure is a partial edit, not a forger with a script; it is not worth
overclaiming.

The one thing it does close: an append cannot repair a tamper. Opening a
journal verifies what is already there, so an edited log cannot be laundered by
the next legitimate write.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from ..contracts.event import GENESIS, Event, EventKind, _Payload

__all__ = [
    "GENESIS",
    "Journal",
    "JournalSealed",
    "JournalTampered",
    "digest_of",
    "read",
    "verify_chain",
]


class JournalSealed(Exception):
    """The log already ended in `CloseCompleted`.

    A finished record cannot be quietly extended. Re-running a close writes a
    new log rather than appending to the old one, so a file always describes
    exactly one close and its terminator always means what it says.
    """


class JournalTampered(Exception):
    """The chain does not hold. Raised rather than reported by default: a log
    that cannot vouch for itself is worse than no log, because it is read as
    evidence."""


def _canonical(event: Event) -> str:
    body = event.model_dump(mode="json", exclude={"event_hash", "prev_hash"})
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def digest_of(event: Event, prev_hash: str) -> str:
    return hashlib.sha256(prev_hash.encode() + _canonical(event).encode()).hexdigest()


def verify_chain(events: list[Event], *, require_terminator: bool = True) -> list[str]:
    """Recompute the chain. Returns one line per problem; empty means it holds."""
    problems: list[str] = []
    prev = GENESIS
    for index, event in enumerate(events):
        if event.seq != index:
            problems.append(f"seq {event.seq} at position {index} — an event is missing or moved")
        if event.prev_hash != prev:
            problems.append(f"seq {event.seq}: prev_hash does not follow seq {index - 1}")
        expected = digest_of(event, event.prev_hash)
        if event.event_hash != expected:
            problems.append(
                f"seq {event.seq} ({event.kind.value}): content does not match its hash"
            )
        prev = event.event_hash

    if require_terminator and (not events or events[-1].kind is not EventKind.CLOSE_COMPLETED):
        # A valid chain over a truncated log is still valid — cutting the tail
        # is the one edit a chain alone cannot see. The terminator is how a
        # short log stays detectable.
        problems.append("the log does not terminate in CloseCompleted — it may be truncated")
    elif events and events[-1].kind is EventKind.CLOSE_COMPLETED:
        declared = events[-1].payload.events_before_this
        if declared != len(events) - 1:
            problems.append(
                f"terminator claims {declared} preceding events, found {len(events) - 1}"
            )
    return problems


def read(path: Path, *, verify: bool = True) -> list[Event]:
    """Read a log. Verifies by default and raises if the chain does not hold.

    The terminator is not required here: a log read while a close is still
    running is legitimately unterminated, and treating that as tampering would
    make the check cry wolf. `verify_chain` requires it, so a *finished* log
    that lost its tail is still caught.
    """
    events = [
        Event.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if verify:
        problems = verify_chain(events, require_terminator=False)
        if problems:
            raise JournalTampered(f"{path}: " + "; ".join(problems[:5]))
    return events


class Journal:
    """Append-only writer. Opening an existing log verifies it first."""

    def __init__(self, path: Path, *, fresh: bool = False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if fresh and self.path.exists():
            # The log records one close. `data/runs/` is local scratch, not an
            # archive — retention is not built, and STATUS says so rather than
            # letting a gitignored directory imply custody it does not have.
            self.path.unlink()
        existing = read(self.path) if self.path.exists() else []
        self._seq = len(existing)
        self._head = existing[-1].event_hash if existing else GENESIS
        self._sealed = bool(existing) and existing[-1].kind is EventKind.CLOSE_COMPLETED

    def append(
        self,
        kind: EventKind,
        *,
        actor: str,
        outcome: str,
        input_hash: str,
        payload: _Payload,
        policy_ref: str | None = None,
        at: datetime | None = None,
    ) -> Event:
        if self._sealed:
            raise JournalSealed(f"{self.path} already ended in CloseCompleted")
        event = Event(
            seq=self._seq,
            kind=kind,
            at=at or datetime.now(UTC),
            actor=actor,
            outcome=outcome,
            input_hash=input_hash,
            policy_ref=policy_ref,
            payload=payload,
            prev_hash=self._head,
        )
        sealed = event.model_copy(update={"event_hash": digest_of(event, self._head)})
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(sealed.model_dump_json() + "\n")
        self._seq += 1
        self._head = sealed.event_hash
        self._sealed = sealed.kind is EventKind.CLOSE_COMPLETED
        return sealed

    def extend(self, events: list[Event]) -> list[Event]:
        """Write a derived batch. The events arrive unsealed; sealing here is
        what keeps hashing in one place."""
        return [
            self.append(
                e.kind,
                actor=e.actor,
                outcome=e.outcome,
                input_hash=e.input_hash,
                payload=e.payload,
                policy_ref=e.policy_ref,
                at=e.at,
            )
            for e in events
        ]

    @property
    def count(self) -> int:
        """Events written so far. Cheaper and less error-prone than re-reading
        the file to count them, which is how the terminator first got an
        off-by-one."""
        return self._seq

    def events(self) -> list[Event]:
        return read(self.path) if self.path.exists() else []
