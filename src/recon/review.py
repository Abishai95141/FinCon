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
from decimal import Decimal
from pathlib import Path

from .contracts import (
    ActorChannel,
    ClassificationAcceptedPayload,
    CloseSignedOffPayload,
    DispositionRecordedPayload,
    EventKind,
    ExceptionAcknowledgedPayload,
    Money,
    ReconException,
)
from .contracts.event import Event
from .journal import Journal, exclusive, read, shared, verify_chain

ZERO = Decimal("0.00")

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

    disposed: dict[str, str] = field(default_factory=dict)
    """exception id -> the disposition a human made. An item in here is *finished*:
    it has an entry behind it and it no longer blocks. Everything else in this
    dataclass records that somebody looked; this one records what was done."""

    disposed_by: dict[str, str] = field(default_factory=dict)
    written_off: Money = ZERO
    """Value that left this close through write-off, running. Read back out of the
    log rather than tracked beside it, because the budget check needs a total the
    next write-off cannot inflate — and computing the same fact twice is how a
    control over one copy goes quietly dead."""

    still_open: int = 0
    """Items left open at sign-off, from the signature's own payload. A signature
    that did not record how much was still outstanding would be a signature on an
    unstated position."""

    signed_off_by: str = ""
    signed_off_at: str = ""
    note: str = ""

    signed_via: ActorChannel = ActorChannel.BROWSER
    """How the signature arrived. Surfaced rather than merely stored: the
    unread-field ratchet refused the field the moment it was added and nothing
    read it, which is exactly the defect it exists to catch — a payload field
    written for an auditor who has no way to see it is a claim with no reader."""

    disposed_via: dict[str, ActorChannel] = field(default_factory=dict)
    """exception id -> the channel its disposition came through."""

    @property
    def signed_off(self) -> bool:
        return bool(self.signed_off_by)

    @property
    def delegated(self) -> int:
        """How many decisions in this close were made through an assistant.

        The number a reviewer actually wants, and the reason the channel is
        recorded at all: not *whether* an agent may act, but how much of this
        close it acted on.
        """
        return sum(1 for c in self.disposed_via.values() if c is ActorChannel.AGENT) + (
            1 if self.signed_via is ActorChannel.AGENT else 0
        )


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
    disposed: dict[str, str] = {}
    disposed_by: dict[str, str] = {}
    disposed_via: dict[str, ActorChannel] = {}
    written_off = ZERO
    still_open = 0
    by = at = note = ""
    signed_via = ActorChannel.BROWSER
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
        elif event.kind is EventKind.DISPOSITION_RECORDED:
            disposed[payload.exception_id] = payload.disposition
            disposed_by[payload.exception_id] = payload.decided_by
            disposed_via[payload.exception_id] = payload.decided_via
            if payload.disposition == "write_off":
                written_off += abs(payload.amount)
        elif event.kind is EventKind.CLOSE_SIGNED_OFF:
            by, at, note = payload.signed_off_by, event.at.isoformat(), payload.note
            still_open = payload.exceptions_open
            signed_via = payload.signed_via
    return Review(
        acknowledged,
        notes,
        accepted,
        accepted_by,
        accepted_from,
        disposed,
        disposed_by,
        written_off,
        still_open,
        by,
        at,
        note,
        signed_via,
        disposed_via,
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

    A **disposed** item clears too, and for a stronger reason than an
    acknowledged one: acknowledgement says a person looked, and a disposition
    says a person acted and an entry followed. Requiring an acknowledgement on
    top of a disposition would make the weaker act gate the stronger one.
    """
    return sorted(
        exc.exception_id
        for exc in exceptions
        if exc.blocks_close
        and exc.exception_id not in review.acknowledged
        and exc.exception_id not in review.disposed
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
    via: ActorChannel = ActorChannel.BROWSER,
) -> Event:
    """A named human accepts the close, or is refused with the reason.

    Three refusals, each a thing that would make the signature meaningless: an
    unnamed signer, books that do not balance, and blocking items nobody has
    looked at. The last is the one that matters — signing off on items you have
    not opened is the exact failure a sign-off exists to prevent.

    **All three bind every channel.** An agent signing under its principal's
    token is refused for unopened blockers exactly as a browser session is —
    the control was never "is this a human", it was "has this been looked at",
    and delegating does not make an unopened item opened. What `via` changes is
    what the record says afterwards, not what is allowed.
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
            signed_via=via,
            acknowledged=len(review.acknowledged),
            exceptions_open=len(exceptions) - len(review.acknowledged),
            note=note.strip(),
        ),
    )


def as_of(run_id: str, runs_dir: Path) -> date | None:
    stream = events(run_id, runs_dir)
    return stream[-1].at.date() if stream else None


def dispose(
    run_id: str,
    runs_dir: Path,
    *,
    decision,
    rationale: str,
    decided_by: str,
    policy_ref: str,
    via: ActorChannel = ActorChannel.BROWSER,
) -> Event:
    """Record a checked disposition. The entry is already built; this is where
    it becomes durable and stops being a thing that happened in a process.

    `decision` is a `recon.disposition.Decision`, which cannot be constructed
    unless it passed every ceiling — so there is no admissibility check here and
    no way to reach this function around one. A second check in this module
    would be the same fact computed twice, and the copy nobody reads is the one
    that rots.

    Refuses a second disposition on the same item: an exception that ends twice
    has had its value removed twice, and the second entry balances just as
    neatly as the first.
    """
    exception = decision.exception
    state = (
        fold(read(path_for(run_id, runs_dir), verify=False))
        if path_for(run_id, runs_dir).exists()
        else None
    )
    if state and exception.exception_id in state.disposed:
        raise ReviewError(
            f"{exception.exception_id} was already {state.disposed[exception.exception_id]} "
            f"by {state.disposed_by.get(exception.exception_id, 'somebody')}. Disposing of it "
            f"again would take its value out of the close a second time."
        )

    entry = decision.entry
    debit = next(p for p in entry.postings if p.amount > ZERO)
    credit = next(p for p in entry.postings if p.amount < ZERO)
    return _append(
        run_id,
        runs_dir,
        EventKind.DISPOSITION_RECORDED,
        actor=decided_by,
        outcome=decision.disposition.value,
        input_hash=exception.fingerprint or exception.exception_id,
        payload=DispositionRecordedPayload(
            exception_id=exception.exception_id,
            fingerprint=exception.fingerprint or "",
            disposition=decision.disposition.value,
            from_code=exception.code,
            amount=abs(exception.amount),
            debit_account=debit.role.value,
            credit_account=credit.role.value,
            entry_id=entry.entry_id,
            decided_by=decided_by,
            decided_via=via,
            rationale=rationale,
            policy_ref=policy_ref,
            ceiling_applied=decision.ceiling,
            budget_remaining=decision.budget_left,
            due_on=decision.due_on,
            owner=decision.owner,
        ),
        policy_ref=policy_ref,
    )


def dispositions(run_id: str, runs_dir: Path) -> list[Event]:
    """Every recorded disposition, oldest first.

    A reader rather than a fold, because the journal needs each event's own
    timestamp and payload and a folded summary would have thrown both away.
    """
    path = path_for(run_id, runs_dir)
    if not path.exists():
        return []
    with shared(path):
        stream = read(path, verify=False)
    return [e for e in stream if e.kind is EventKind.DISPOSITION_RECORDED]
