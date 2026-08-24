"""Reconstruct a close from its decision log, and nothing else.

The gate is that this produces the same scorecard the run did. Two ways to fake
that, both closed here:

**Logging the answer.** If the log carried the scorecard, replay would be a
`json.load`. It carries decisions; the scorecard is recomputed from them against
the same labels the run was always scored on.

**Replaying by re-running.** A replay that calls the engine measures the engine.
This module imports no matcher, no solver and no blocker — asserted structurally
in the gate, and again by making the engine raise while a replay runs.

The record-id -> external-id map is rebuilt from the events themselves rather
than from a header blob, so the map a replay holds is exactly the one the events
justify. That is only total because the derivation refuses to finish while any
disposed input is unnamed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..contracts import ExceptionCode, ReconException
from ..contracts.event import Event, EventKind


@dataclass(frozen=True)
class ReplayedClose:
    batch: str = ""
    profile: str = ""
    policy_ref: str | None = None
    policy_digest: str = ""
    source_digests: dict[str, str] = field(default_factory=dict)
    label_digest: str | None = None

    pairs: dict[str, frozenset[str]] = field(default_factory=dict)
    """Anchor external id -> the external ids claimed to back it, exactly the
    shape an arm reports, so the same scorer runs over it unchanged."""

    tiers: dict[str, int] = field(default_factory=dict)
    rejected: list[str] = field(default_factory=list)
    exceptions: list[ReconException] = field(default_factory=list)
    out_of_scope: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    unverified: dict[str, str] = field(default_factory=dict)
    postings: list[dict[str, str]] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    external_of: dict[str, str] = field(default_factory=dict)
    terminated: bool = False
    declared_counts: dict[str, int] = field(default_factory=dict)


def replay(events: list[Event]) -> ReplayedClose:
    header = next((e for e in events if e.kind is EventKind.CLOSE_STARTED), None)
    external_of: dict[str, str] = {}
    for event in events:
        external_of.update(event.payload.externals())

    pairs: dict[str, frozenset[str]] = {}
    tiers: dict[str, int] = {}
    rejected: list[str] = []
    exceptions: list[ReconException] = []
    out_of_scope: dict[str, str] = {}
    sources: dict[str, str] = {}
    unverified: dict[str, str] = {}
    postings: list[dict[str, str]] = []
    blocked: list[str] = []
    terminated = False
    declared: dict[str, int] = {}

    for event in events:
        payload = event.payload
        match event.kind:
            case EventKind.MATCH_PROVEN:
                anchor = external_of.get(payload.anchor_id, payload.anchor_id)
                pairs[anchor] = frozenset(external_of.get(rid, rid) for rid in payload.group_ids)
                tiers[payload.tier] = tiers.get(payload.tier, 0) + 1
            case EventKind.MATCH_REJECTED:
                rejected.append(f"{payload.match_id}: {'; '.join(payload.reasons)}")
            case EventKind.EXCEPTION_RAISED:
                exceptions.append(
                    ReconException(
                        exception_id=payload.exception_id,
                        code=ExceptionCode(payload.code),
                        as_of=date.fromisoformat(payload.as_of),
                        amount=payload.amount,
                        leg=payload.leg,
                        record_ids=list(payload.named_records),
                        alternatives=payload.alternatives,
                        hypothesis=payload.hypothesis,
                        evidence=list(payload.evidence),
                        blocks_close=payload.blocks_close,
                    )
                )
            case EventKind.OUT_OF_SCOPE:
                out_of_scope[payload.record_id] = payload.reason
            case EventKind.SOURCE_INGESTED:
                sources[payload.source] = payload.strength
            case EventKind.INTAKE_UNVERIFIED:
                sources[payload.source] = payload.strength
                unverified[payload.source] = payload.gap
            case EventKind.POSTING_WRITTEN:
                postings.append(
                    {
                        "entry_id": payload.entry_id,
                        "origin": payload.proof_id or payload.exception_id or "",
                        "residual": f"{_residual(payload.postings):.2f}",
                    }
                )
            case EventKind.CLOSE_BLOCKED:
                blocked.extend(payload.reasons)
            case EventKind.CLOSE_COMPLETED:
                terminated = True
                declared = {
                    "matches": payload.matches,
                    "rejected": payload.rejected,
                    "exceptions": payload.exceptions,
                    "postings": payload.postings,
                    "out_of_scope": payload.out_of_scope,
                }
            case _:
                pass

    return ReplayedClose(
        batch=header.payload.batch if header else "",
        profile=header.payload.profile if header else "",
        policy_ref=header.policy_ref if header else None,
        policy_digest=header.payload.policy_digest if header else "",
        source_digests=dict(header.payload.source_digests) if header else {},
        label_digest=header.payload.label_digest if header else None,
        pairs=pairs,
        tiers=tiers,
        rejected=rejected,
        exceptions=exceptions,
        out_of_scope=out_of_scope,
        sources=sources,
        unverified=unverified,
        postings=postings,
        blocked=blocked,
        external_of=external_of,
        terminated=terminated,
        declared_counts=declared,
    )


def _residual(postings: list[dict[str, str]]) -> Decimal:
    return sum((Decimal(p["amount"]) for p in postings), Decimal("0.00"))


def disagreements(replayed: ReplayedClose) -> list[str]:
    """Where the log's own terminator disagrees with what the events contain.

    The counts in the terminator are a *claim by the writer*. Checking them
    against the replayed stream is the same propose/verify shape as everything
    else here — and the reason to keep them at all, since replay never reads
    them for its answer.
    """
    if not replayed.terminated:
        return ["the log does not terminate — nothing to check the stream against"]
    actual = {
        "matches": len(replayed.pairs),
        "rejected": len(replayed.rejected),
        "exceptions": len(replayed.exceptions),
        "postings": len(replayed.postings),
        "out_of_scope": len(replayed.out_of_scope),
    }
    return [
        f"terminator claims {n} {key}, the stream contains {actual[key]}"
        for key, n in replayed.declared_counts.items()
        if actual[key] != n
    ]
