"""Lifecycle transitions for the exception-code registry.

The registry itself is a frozen contract that answers questions. This is what
may *change* it, and it lives here for the same reason `promotion` does: a
contract states what is true, an engine module states what a named actor is
allowed to do about it and writes the fact down.

Every transition returns a new registry. Nothing mutates in place, so a caller
holding the old one keeps holding exactly what it was judged under — which is
what makes a decision log replayable against the vocabulary of its own run.

The lifecycle is walked in order. `PROPOSED -> PROVISIONAL -> PROMOTED` cannot
be short-circuited: jumping straight to full authority is precisely the thing
the intermediate step exists to withhold.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..contracts.event import (
    CodeAcceptedPayload,
    CodePromotedPayload,
    CodeProposedPayload,
    EventKind,
    ProposalRefusedPayload,
)
from ..contracts.taxonomy import (
    MIN_DEFINITION,
    CodeDefinition,
    CodeStatus,
    TaxonomyRegistry,
    TaxonomyViolation,
)

AGENT_NAMESPACE = "X-"


def _record(journal, kind, **fields) -> None:
    if journal is not None:
        journal.append(kind, **fields)


def _refuse(journal, code: str, actor: str, reasons: list[str]) -> TaxonomyViolation:
    """Write the refusal, then hand back the error for the caller to raise.

    Recorded before it is raised, for the reason `promote()` does the same: in a
    governed system the refusal is the interesting event, and a log containing
    only what succeeded is a marketing document.
    """
    _record(
        journal,
        EventKind.PROPOSAL_REFUSED,
        actor=actor or "unknown",
        outcome="refused",
        input_hash=code,
        payload=ProposalRefusedPayload(
            subject=code, proposal_kind="exception_code", reasons=reasons
        ),
    )
    return TaxonomyViolation(f"refused {code}: " + "; ".join(reasons))


def _with(registry: TaxonomyRegistry, entry: CodeDefinition) -> TaxonomyRegistry:
    return registry.model_copy(
        update={"codes": {**registry.codes, entry.code: entry}, "version": registry.version + 1}
    )


def propose(
    registry: TaxonomyRegistry,
    *,
    code: str,
    title: str,
    definition: str,
    actor: str,
    owner: str | None = None,
    books_to: str | None = None,
    journal: object | None = None,
    **ignored,
) -> TaxonomyRegistry:
    """Mint a code with no authority.

    `**ignored` is deliberate and load-bearing: a proposal may arrive carrying
    `status: promoted` and `promoted_by: nobody`, and those fields are dropped
    on the floor rather than validated. The status is *assigned here*, never
    read from the proposal — audit finding `F1` in a taxonomy costume.
    """
    reasons: list[str] = []
    if not (actor or "").strip():
        reasons.append("a proposal must name who made it")
    if code in registry:
        reasons.append(f"{code} already exists as {registry[code].status.value}")
    if not code.startswith(AGENT_NAMESPACE) and actor != registry.approved_by:
        # A canonical `E**` id sits beside codes a human ratified. Anything
        # discovered later keeps its `X-` origin in its id forever, because
        # renaming on promotion would break every reference already written.
        reasons.append(
            f"{code} is outside the {AGENT_NAMESPACE!r} namespace; only the "
            f"taxonomy approver mints canonical codes"
        )
    if reasons:
        raise _refuse(journal, code, actor, reasons)

    entry = CodeDefinition(
        code=code,
        title=title,
        definition=definition,
        status=CodeStatus.PROPOSED,
        owner=owner,
        books_to=books_to,
        proposed_by=actor,
        proposed_at=datetime.now(UTC),
    )
    _record(
        journal,
        EventKind.CODE_PROPOSED,
        actor=actor,
        outcome="proposed",
        input_hash=code,
        payload=CodeProposedPayload(
            code=code,
            title=title,
            definition=definition,
            claimed_owner=owner,
            claimed_booking=books_to,
            routed_to=registry.default_owner,
            granted=entry.authority.summary(),
        ),
    )
    return _with(registry, entry)


def accept(
    registry: TaxonomyRegistry,
    code: str,
    *,
    actor: str,
    owner: str,
    journal: object | None = None,
) -> TaxonomyRegistry:
    """A named human agrees this is a real category and gives it a queue.

    Still no decision-making power: routing work to a person who can judge it is
    exactly the amount of authority a category deserves before anyone has
    written down what it means.
    """
    entry = registry[code]
    reasons: list[str] = []
    if not (actor or "").strip():
        reasons.append("an acceptance must name who granted it")
    if not (owner or "").strip():
        reasons.append("an acceptance must name the queue that will work it")
    if entry.status is not CodeStatus.PROPOSED:
        reasons.append(f"{code} is {entry.status.value}, not proposed")
    if reasons:
        raise _refuse(journal, code, actor, reasons)

    updated = entry.model_copy(
        update={
            "status": CodeStatus.PROVISIONAL,
            "owner": owner,
            "accepted_by": actor,
            "accepted_at": datetime.now(UTC),
        }
    )
    _record(
        journal,
        EventKind.CODE_ACCEPTED,
        actor=actor,
        outcome="accepted",
        input_hash=code,
        payload=CodeAcceptedPayload(code=code, owner=owner, granted=updated.authority.summary()),
    )
    return _with(registry, updated)


def promote(
    registry: TaxonomyRegistry,
    code: str,
    *,
    actor: str,
    definition: str,
    books_to: str | None = None,
    journal: object | None = None,
) -> TaxonomyRegistry:
    """Ratify. This is the step that grants power, so it costs the most.

    A named human and a written definition, both checked here rather than
    trusted from the record: a promotion is the moment a category starts routing
    money, and "fx thing" is not a specification other people can work by.
    """
    entry = registry[code]
    reasons: list[str] = []
    if not (actor or "").strip():
        reasons.append("a promotion must name who granted it")
    if entry.status is not CodeStatus.PROVISIONAL:
        reasons.append(
            f"{code} is {entry.status.value}; a code must be provisional before it "
            f"is promoted — the intermediate step is where a human decides it is real"
        )
    if len((definition or "").strip()) < MIN_DEFINITION:
        reasons.append(
            f"a promotion needs a written definition of at least {MIN_DEFINITION} "
            f"characters, got {len((definition or '').strip())}"
        )
    if reasons:
        raise _refuse(journal, code, actor, reasons)

    updated = entry.model_copy(
        update={
            "status": CodeStatus.PROMOTED,
            "definition": definition,
            "books_to": books_to or entry.books_to,
            "promoted_by": actor,
            "promoted_at": datetime.now(UTC),
        }
    )
    _record(
        journal,
        EventKind.CODE_PROMOTED,
        actor=actor,
        outcome="promoted",
        input_hash=code,
        payload=CodePromotedPayload(
            code=code,
            definition=definition,
            owner=updated.owner,
            books_to=updated.books_to,
            granted=updated.authority.summary(),
        ),
    )
    return _with(registry, updated)


def retire(
    registry: TaxonomyRegistry,
    code: str,
    *,
    actor: str,
    superseded_by: str | None = None,
    journal: object | None = None,
) -> TaxonomyRegistry:
    """Stop a code being assigned without making the record unreadable.

    A retired code still resolves and still labels. Retiring one that then
    stopped resolving would break last quarter's decision log by the act of
    tidying up this quarter's vocabulary.
    """
    entry = registry[code]
    reasons: list[str] = []
    if not (actor or "").strip():
        reasons.append("a retirement must name who did it")
    if superseded_by and superseded_by not in registry:
        reasons.append(f"{superseded_by} is not a code in {registry.ref}")
    if reasons:
        raise _refuse(journal, code, actor, reasons)

    updated = entry.model_copy(
        update={
            "status": CodeStatus.RETIRED,
            "retired_at": datetime.now(UTC),
            "superseded_by": superseded_by,
        }
    )
    return _with(registry, updated)
