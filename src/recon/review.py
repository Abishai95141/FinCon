"""The human half of a close, in its own chained record.

`decisions.jsonl` seals at `CloseCompleted` and that is correct: it is what the
*engine* decided, and a finished record must not be quietly extended. What a
person decides afterwards is a different thing, so it goes in a different file —
`review.jsonl`, same hash chain, same `Event` contract, linked by run id.

Two records, and the separation is the point. A close that finished is not a
close somebody approved, and until this module existed the product showed one as
the other: the scorecard said `complete`, the page said "Needs review", and there
was no way to review anything. That is a product claiming an approval nobody gave.

**Acknowledging is not resolving.** Nothing about the close changes, no posting
moves, and the money is still unreconciled. What changes is that a named human is
accountable for the item — which is the entire content of `P2 ATTESTED`, and the
most this build can honestly offer. Resolving an item *with a posting* needs the
attestation path into the ledger and is its own phase; `STATUS.md` says so rather
than letting a button imply it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .contracts import (
    ClassificationAcceptedPayload,
    CloseSignedOffPayload,
    EventKind,
    ExceptionAcknowledgedPayload,
    ReconException,
)
from .contracts.event import Event
from .journal import Journal, exclusive, read, shared, verify_chain

FILENAME = "review.jsonl"


class ReviewError(ValueError):
    """A review action this system will not take, with the reason kept."""


def path_for(run_id: str, runs_dir: Path) -> Path:
    return runs_dir / run_id / FILENAME


def events(run_id: str, runs_dir: Path) -> list[Event]:
    """Everything a human has done to this close. Empty is a real state — an
    unreviewed close, which is what every close starts as."""
    path = path_for(run_id, runs_dir)
    if not path.exists():
        return []
    with shared(path):
        return read(path, verify=False)


def problems(run_id: str, runs_dir: Path) -> list[str]:
    """Whether the review record vouches for itself.

    `require_terminator=False`: a review log is legitimately unfinished right up
    until somebody signs off, and treating that as tampering would make the
    check cry wolf on every close in progress.
    """
    stream = events(run_id, runs_dir)
    return verify_chain(stream, require_terminator=False) if stream else []


@dataclass(frozen=True)
class Review:
    """What a human has done, as the surface needs to render it."""

    acknowledged: dict[str, str]
    """exception id -> who took it."""

    notes: dict[str, str]
    accepted: dict[str, str]
    """exception id -> the code a human accepted for it."""

    accepted_by: dict[str, str] = field(default_factory=dict)
    accepted_from: dict[str, str] = field(default_factory=dict)
    """What the code was before a human changed it, and who changed it. Carried
    so the item page can say "X moved this from E14 to E01" rather than showing
    a code with no history — a reclassification with no before and no name is
    exactly the anonymous relabel this project refuses."""

    still_open: int = 0
    """Items left open at sign-off, from the signature's own payload. A signature
    that did not record how much was still outstanding would be a signature on an
    unstated position."""

    signed_off_by: str = ""
    signed_off_at: str = ""
    note: str = ""

    @property
    def signed_off(self) -> bool:
        return bool(self.signed_off_by)


def state(run_id: str, runs_dir: Path) -> Review:
    """Fold the review log into the current state. Derived, never stored — a
    stored summary beside an append-only log is the copy that rots."""
    return fold(events(run_id, runs_dir))


def fold(stream: list[Event]) -> Review:
    """The same fold over events already in hand.

    Split out because `_append` needs the state *while holding the write lock*,
    and calling `state()` there self-deadlocked: `flock` refuses a shared lock
    against an exclusive one on the same file, and does not care that both are
    this process. It hung for the full 30-second wait and then reported a stuck
    writer, which is a truthful message about a lock and a useless one about the
    bug.
    """
    acknowledged: dict[str, str] = {}
    notes: dict[str, str] = {}
    accepted: dict[str, str] = {}
    accepted_by: dict[str, str] = {}
    accepted_from: dict[str, str] = {}
    still_open = 0
    by = at = note = ""
    for event in stream:
        payload = event.payload
        if event.kind is EventKind.EXCEPTION_ACKNOWLEDGED:
            acknowledged[payload.exception_id] = payload.acknowledged_by
            if payload.note:
                notes[payload.exception_id] = payload.note
        elif event.kind is EventKind.CLASSIFICATION_ACCEPTED:
            accepted[payload.exception_id] = payload.to_code
            accepted_by[payload.exception_id] = payload.accepted_by
            accepted_from[payload.exception_id] = payload.from_code
        elif event.kind is EventKind.CLOSE_SIGNED_OFF:
            by, at, note = payload.signed_off_by, event.at.isoformat(), payload.note
            still_open = payload.exceptions_open
    return Review(
        acknowledged, notes, accepted, accepted_by, accepted_from, still_open, by, at, note
    )


def _append(
    run_id: str,
    runs_dir: Path,
    kind: EventKind,
    *,
    actor: str,
    outcome: str,
    input_hash: str,
    payload,
    policy_ref: str | None,
) -> Event:
    path = path_for(run_id, runs_dir)
    with exclusive(path):
        existing = read(path, verify=False) if path.exists() else []
        if fold(existing).signed_off:
            raise ReviewError(
                f"{run_id} is signed off. A signed close is a statement somebody "
                f"made; changing it afterwards would make the statement worthless. "
                f"Re-close the period to produce a new record."
            )
        return Journal(path).append(
            kind,
            actor=actor,
            outcome=outcome,
            input_hash=input_hash,
            payload=payload,
            policy_ref=policy_ref,
        )


def acknowledge(
    run_id: str,
    runs_dir: Path,
    *,
    exception: ReconException,
    by: str,
    note: str = "",
    policy_ref: str | None = None,
) -> Event:
    """A named human takes an item.

    `by` is a person. An acknowledgement from "system" answers the wrong
    question — the point of `P2` is that somebody is accountable.
    """
    if not by.strip():
        raise ReviewError("an acknowledgement needs a name; 'who took this' is the point")
    return _append(
        run_id,
        runs_dir,
        EventKind.EXCEPTION_ACKNOWLEDGED,
        actor=by,
        outcome="acknowledged",
        input_hash=exception.exception_id,
        policy_ref=policy_ref,
        payload=ExceptionAcknowledgedPayload(
            exception_id=exception.exception_id,
            fingerprint=exception.fingerprint,
            code=exception.code,
            acknowledged_by=by,
            note=note.strip(),
        ),
    )


def accept_classification(
    run_id: str,
    runs_dir: Path,
    *,
    exception: ReconException,
    to_code: str,
    by: str,
    hypothesis: str = "",
    model: str = "",
    policy_ref: str | None = None,
) -> Event:
    """A human takes a proposed code.

    The proposal itself moved nothing — a model proposal is `P2 ATTESTED` at
    best, and this is the step that makes it so. Refused outright where the
    engine *derived* the label: a proposal may not overwrite a higher proof tier,
    and `E09` proved by enumerating two valid subsets is exactly that.
    """
    from .triage.classify import reclassifiable

    if not by.strip():
        raise ReviewError("an attestation needs a named human")
    if not reclassifiable(exception):
        raise ReviewError(
            f"{exception.exception_id} carries {exception.code} at "
            f"{exception.code_provenance.value} — the engine derived it, and a "
            f"proposal cannot overwrite a higher proof tier."
        )
    return _append(
        run_id,
        runs_dir,
        EventKind.CLASSIFICATION_ACCEPTED,
        actor=by,
        outcome="accepted",
        input_hash=exception.exception_id,
        policy_ref=policy_ref,
        payload=ClassificationAcceptedPayload(
            exception_id=exception.exception_id,
            from_code=exception.code,
            to_code=to_code,
            accepted_by=by,
            hypothesis=hypothesis,
            model=model,
        ),
    )


def blockers(exceptions: list[ReconException], review: Review) -> list[str]:
    """Items that must be taken before anyone may sign off.

    Only the ones the engine marked `blocks_close`. An ordinary exception is the
    normal state of a real close and holding sign-off on all of them would make
    the control theatre nobody could satisfy.
    """
    return sorted(
        exc.exception_id
        for exc in exceptions
        if exc.blocks_close and exc.exception_id not in review.acknowledged
    )


def sign_off(
    run_id: str,
    runs_dir: Path,
    *,
    exceptions: list[ReconException],
    outcome_digest: str,
    by: str,
    note: str = "",
    books_blocked: list[str] | None = None,
    policy_ref: str | None = None,
) -> Event:
    """A named human accepts the close, or is refused with the reason.

    Three refusals, each a thing that would make the signature meaningless: an
    unnamed signer, books that do not balance, and blocking items nobody has
    looked at. The last is the one that matters — signing off on items you have
    not opened is the exact failure a sign-off exists to prevent.
    """
    if not by.strip():
        raise ReviewError("a sign-off needs a named human; that is the whole content of it")
    if books_blocked:
        raise ReviewError(
            "the books do not balance: " + "; ".join(books_blocked) + ". "
            "Signing off on a close that does not tie would put a name to a "
            "number the system itself says is wrong."
        )
    review = state(run_id, runs_dir)
    unopened = blockers(exceptions, review)
    if unopened:
        raise ReviewError(
            f"{len(unopened)} blocking item(s) nobody has taken: {', '.join(unopened[:4])}"
            f"{'…' if len(unopened) > 4 else ''}. Acknowledge them first — signing "
            f"off on items you have not opened is what this control exists to stop."
        )
    return _append(
        run_id,
        runs_dir,
        EventKind.CLOSE_SIGNED_OFF,
        actor=by,
        outcome="signed_off",
        input_hash=outcome_digest,
        policy_ref=policy_ref,
        payload=CloseSignedOffPayload(
            run_id=run_id,
            outcome_digest=outcome_digest,
            signed_off_by=by,
            acknowledged=len(review.acknowledged),
            exceptions_open=len(exceptions) - len(review.acknowledged),
            note=note.strip(),
        ),
    )


def as_of(run_id: str, runs_dir: Path) -> date | None:
    stream = events(run_id, runs_dir)
    return stream[-1].at.date() if stream else None
