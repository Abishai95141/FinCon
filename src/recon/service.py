"""The application service — one implementation, two surfaces over it.

`src/recon/api/` and `src/recon/mcp/` were 0-byte files for thirteen phases. The
temptation when they stop being empty is to write the close pipeline twice, once
per protocol, and the result is the banned pattern at the top of CLAUDE.md: a
demo path that differs from the real path. So HTTP and MCP are **driving
adapters**. Neither holds a decision; both call functions here, and these call
`recon.loop.run`, `recon.journal`, `recon.engine.verifier` and
`recon.triage.worklist`. The same test asserts an HTTP body and an MCP tool
result are byte-identical, which is what makes "one code path" checkable rather
than stated.

Three properties this boundary is built to hold.

**Authority is never a request parameter.** Nothing here accepts a policy, a
tolerance, a sign convention or a rule set on the way *in* to a close. Those are
loaded from the loop's own signed bundles. An HTTP client and an MCP client are
both callers, and the MCP caller may be a model — so the boundary has to be
structural, not conventional. `tests/property/test_surface_authority.py` walks
every tool and route signature and fails on a parameter that could carry one.

**Everything a surface shows has been through the durable record.** `close()`
runs a close and then reads back the log it just wrote; `view()` reads a log
written earlier. There is one path from record to screen, so a fact that reaches
a controller is a fact an auditor can re-derive from the same file. The chain is
verified on every read.

**Verification is stateless and says whose constraints it applied.** `check()`
re-derives a proof from records the caller supplies. A caller may name a
published policy or hand in their own; the verdict is stamped with which, so a
lenient policy someone brought along cannot be quoted back as our verdict.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from . import loop as looplib
from . import trust
from .contracts import (
    CONTRACT_VERSION,
    CodeStatus,
    Policy,
    Proof,
    ReconException,
    Record,
    TaxonomyRegistry,
)
from .contracts.event import Event
from .engine.verifier import verify as verify_proof
from .journal import read as read_journal
from .journal import shared as journal_lock
from .journal import verify_chain
from .journal.replay import ReplayedClose, disagreements, replay, unproven
from .triage.classify import check_proposal
from .triage.worklist import build as build_worklist

#: The surface's own version. The *contracts* embedded in these envelopes carry
#: their own `contract_version` and are semver'd under ADR-002; this versions the
#: envelope around them. They move independently on purpose — adding a field to
#: a response must not be able to look like a contract change.
API_VERSION = "v1"

#: Where source sets are dropped. An environment variable because it is the one
#: genuine deployment knob on this surface — a bank's feed writes somewhere, and
#: that somewhere is not our business. Note what is *not* configurable here:
#: policy, tolerances, the taxonomy and the rule store all come from the loop's
#: signed bundles, so no operator setting can widen what a close is permitted to
#: accept.
BATCH_ROOT = Path(os.environ.get("RECON_SOURCE_ROOT", "data/batches"))

#: The most one paged collection may weigh. An MCP tool result goes straight
#: into a model's context window, and this surface shipped with `run_match`
#: returning 397 KB — roughly 100k tokens, most of a context, for 543 rows of a
#: toy corpus. Tested and unusable are different things.
#:
#: A **byte** budget rather than a row count, because the rows differ in size by
#: two orders of magnitude: a proof with 39 record ids and an out-of-scope note
#: are both "one item". A count tuned for one is wrong for the other, and the
#: symptom is a limit that works until the day someone's payout has more rows.
RESULT_BUDGET = 24 * 1024

#: What any single tool result must stay under, asserted over every tool in
#: `tests/property/test_result_budget.py`. Higher than RESULT_BUDGET because a
#: response is an envelope plus a page, not a page alone.
TOOL_BUDGET = 64 * 1024


class Detail(StrEnum):
    """How much of a close to return.

    `SUMMARY` is the default everywhere, including for a browser. The full
    proofs are 46 KB of the 58 KB a close view used to weigh, and almost no
    caller needs all twenty at once — a reader opens one row. `get_proof` and
    `GET /v1/runs/{id}/matches/{match_id}/proof` return one, in full, and a
    summary row names the `proof_id` so there is always something to ask for.
    """

    SUMMARY = "summary"
    FULL = "full"


class Page[T](BaseModel):
    """A slice of a collection that always says what it left out.

    CLAUDE.md bans a silent cap: "if a workflow bounds coverage, log what was
    dropped — silent truncation reads as 'covered everything' when it didn't."
    A paged API is the same hazard with a nicer name, so `total` is always the
    real total, `next_offset` is present exactly when more remain, and
    `stopped_at_budget` says whether the page ended because the caller asked or
    because the bytes ran out.
    """

    model_config = ConfigDict(frozen=True)

    items: list[T]
    total: int
    offset: int
    returned: int
    next_offset: int | None = None
    stopped_at_budget: bool = False
    budget_bytes: int = RESULT_BUDGET

    @property
    def complete(self) -> bool:
        return self.next_offset is None


def paginate(
    items: Sequence, *, offset: int = 0, limit: int | None = None, budget: int = RESULT_BUDGET
) -> dict:
    """Take items from `offset` until the caller's limit or the byte budget.

    Serialised size is measured as items are added rather than estimated, so an
    unusually fat row is caught by the thing it would break. At least one item
    is always returned even if it alone exceeds the budget — a page that could
    return nothing would make a single large record permanently unreachable,
    which is a worse failure than a big response.
    """
    total = len(items)
    if offset < 0 or offset > total:
        raise ServiceError(f"offset {offset} is outside a collection of {total}")

    taken: list = []
    size = 0
    stopped = False
    for item in items[offset : total if limit is None else offset + max(limit, 0)]:
        encoded = len(json.dumps(item, default=str))
        if taken and size + encoded > budget:
            stopped = True
            break
        taken.append(item)
        size += encoded

    consumed = offset + len(taken)
    return {
        "items": taken,
        "total": total,
        "offset": offset,
        "returned": len(taken),
        "next_offset": consumed if consumed < total else None,
        "stopped_at_budget": stopped,
        "budget_bytes": budget,
    }


class ServiceError(ValueError):
    """A request this service will not serve. Distinguished from a bug: the
    surfaces turn it into a 4xx / a tool error with the reason intact, and never
    into a default that quietly closes something else."""


# --------------------------------------------------------------------------
# what a loop is, and what it can close
# --------------------------------------------------------------------------


class SourceView(BaseModel):
    model_config = ConfigDict(frozen=True)

    spec_id: str
    filename: str
    side: str
    role: str


class LoopView(BaseModel):
    """A reconciliation loop as a caller sees it, before any close is run."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    period_start: date
    period_end: date
    policy_ref: str
    taxonomy_ref: str
    strategies: list[str]
    """The ways this loop may match, in the order it tries them. Published
    because it is the loop's behaviour, declared as data (P15a) — a caller can
    see *how* a match would be attempted before asking for one."""

    sources: list[SourceView]
    promoted_rules: list[str]


class SourceSetView(BaseModel):
    """One period's worth of files, and whether they all arrived."""

    model_config = ConfigDict(frozen=True)

    name: str
    complete: bool
    present: list[str]
    missing: list[str]
    """Named, not counted. "settlement.csv has not arrived" is actionable;
    "1 source missing" is not — and a close over a half-arrived period would
    report a clean month over rows that never came."""


def loops() -> list[LoopView]:
    from .engine import rulestore

    out: list[LoopView] = []
    for lp in looplib.all_loops():
        pol = lp.policy()
        out.append(
            LoopView(
                name=lp.name,
                description=lp.description,
                period_start=lp.period[0],
                period_end=lp.period[1],
                policy_ref=pol.ref,
                taxonomy_ref=lp.taxonomy().ref,
                strategies=list(lp.profile.strategies),
                sources=[
                    SourceView(spec_id=b.spec_id, filename=b.filename, side=b.side, role=b.role)
                    for b in lp.sources
                ],
                promoted_rules=[r.ref for r in rulestore.load(lp.profile.name)],
            )
        )
    return out


def source_sets(loop_name: str, root: Path | None = None) -> list[SourceSetView]:
    """Every directory under `root`, complete or not.

    Incomplete ones are listed rather than hidden. A surface that only showed
    closeable periods would answer "where is October?" with silence, which is
    the same failure mode as a filter before the completeness audit: the
    interesting case is the one that went missing.
    """
    lp = looplib.get(loop_name)
    base = root or BATCH_ROOT
    if not base.exists():
        return []
    out: list[SourceSetView] = []
    for directory in sorted(d for d in base.iterdir() if d.is_dir()):
        missing = lp.missing(directory)
        out.append(
            SourceSetView(
                name=directory.name,
                complete=not missing,
                present=[f for f in lp.filenames if f not in missing],
                missing=missing,
            )
        )
    return out


# --------------------------------------------------------------------------
# a close, as a surface renders it — read back from the record
# --------------------------------------------------------------------------


class BlockingView(BaseModel):
    """What blocking did, and the one number production cannot have.

    Invariant 6 says blocking recall is reported on every run, and recall is
    measured against *labelled* true pairs. In production nobody has the labels
    — that is the whole problem — so recall here is **absent**, not zero, and
    says what would measure it. A zero would read as "we ran it and found
    nothing", which is a claim, and it would flatter us for free.
    """

    model_config = ConfigDict(frozen=True)

    considered: int
    exhaustive: int
    reduction: str
    recall: None = None
    recall_note: str = (
        "absent — blocking recall is measured against labelled true pairs, which "
        "production does not have. Measured in the benchmark (`make eval`), where "
        "labels are authored at P0."
    )


class TierSplit(BaseModel):
    """A headline number never ships without its decomposition."""

    model_config = ConfigDict(frozen=True)

    matched: int
    anchors_in_scope: int
    """Anchors the matcher was offered, from the record's own header. `0` means
    a log written before contract 7.4.0, which recorded only what came out — a
    numerator with no denominator, which is not a rate."""

    rate: str
    by_match_tier: dict[str, int]
    by_proof_tier: dict[str, int]
    declared: int
    """Matches resting on a stated gap rather than on arithmetic. Broken out
    because a match rate that mixes them in is the gameable headline."""


class ExceptionView(BaseModel):
    """One item on the tail, with everything needed to work it."""

    model_config = ConfigDict(frozen=True)

    rank: int
    exception: ReconException
    code_title: str
    code_status: CodeStatus
    owner: str
    authority_note: str | None = None
    """Set when the code is not ratified. A worklist rendering a proposed
    category identically to a promoted one hides the one thing the reader needs
    to calibrate trust."""

    cash_impact_paise: int
    age_days: int


class MatchView(BaseModel):
    """One proven match and the proof a third party re-derives it from."""

    model_config = ConfigDict(frozen=True)

    match_id: str
    tier: str
    anchor_id: str
    anchor_external: str
    group_ref: str
    group_ids: list[str]
    proof: Proof | None = None
    proof_id: str = ""
    group_size: int = 0
    proof_omitted: str = ""
    """Why the proof is not here. Empty means it is.

    Withheld is not the same as missing, and the two must never render alike: a
    proof the record does not contain is a finding (`CloseView.unproven_matches`),
    while one this response chose not to inline is a fetch away. So a summary row
    says which, and names the call that returns it."""


class CloseView(BaseModel):
    """A whole close, assembled from its decision log.

    Not from the in-memory outcome. `close()` runs the pipeline and then reads
    the file back through this same function, so a controller and an auditor are
    looking at one artifact. If the record cannot say it, the screen does not
    show it — which is how P13 found that a rule breaking a match, and a rule
    refused as inadmissible, reached the log nowhere at all.
    """

    model_config = ConfigDict(frozen=True)

    api_version: str = API_VERSION
    contract_version: str = CONTRACT_VERSION
    run_id: str
    loop: str
    policy_ref: str | None
    policy_digest: str
    period: list[str] = Field(default_factory=list)

    complete: bool
    """Invariant 8 — every input got a disposition. A close can be complete and
    still need work; the two are different questions and are answered
    separately."""

    blocked: list[str]
    """Close-level blockers: the books do not balance, or a rule broke a match
    it should not have. Distinct from `blocking_exceptions` below, which is a
    queue of items for a human — the record used to collapse the two."""

    blocking_exceptions: list[str] = Field(default_factory=list)
    ok: bool

    tiers: TierSplit
    matches: list[MatchView]
    rejected: list[str]
    exceptions: list[ExceptionView]
    out_of_scope: dict[str, str]
    sources: dict[str, str]
    unverified: dict[str, str]
    postings: int
    authority: list[dict] = Field(default_factory=list)
    rules_applied: list[dict] = Field(default_factory=list)
    rules_refused: list[dict] = Field(default_factory=list)

    chain_problems: list[str] = Field(default_factory=list)
    """Empty means the log's hash chain holds and its terminator agrees with the
    stream. Non-empty is served anyway, loudly: a surface that refused to render
    a tampered log would leave the reader with nothing to look at and no idea
    why."""

    unproven_matches: list[str] = Field(default_factory=list)
    """Matches whose proof the record does not contain — a log written before
    contract 7.4.0. Absent evidence, named, rather than a match that looks fine
    because nothing was checked."""

    events: int = 0


def runs_root(runs_dir: Path | None = None) -> Path:
    return runs_dir or looplib.RUNS


def stored_runs(runs_dir: Path | None = None) -> list[str]:
    base = runs_root(runs_dir)
    if not base.exists():
        return []
    return sorted(d.name for d in base.iterdir() if (d / "decisions.jsonl").exists())


def _log_path(run_id: str, runs_dir: Path | None = None) -> Path:
    if "/" in run_id or "\\" in run_id or run_id in {"", ".", ".."}:
        raise ServiceError(f"{run_id!r} is not a run id")
    path = runs_root(runs_dir) / run_id / "decisions.jsonl"
    if not path.exists():
        raise ServiceError(f"no decision log for run {run_id!r} at {path}")
    return path


def events(run_id: str, runs_dir: Path | None = None) -> list[Event]:
    """The typed event stream, verified on the way out.

    `verify=False` on the read and `verify_chain` afterwards, deliberately: a
    tampered log is served with its problems attached rather than withheld. The
    caller is auditing us; hiding the evidence of tampering from them would be
    an odd way to prove we are honest.
    """
    path = _log_path(run_id, runs_dir)
    with journal_lock(path):
        return read_journal(path, verify=False)


def view(
    run_id: str, runs_dir: Path | None = None, *, detail: Detail = Detail.SUMMARY
) -> CloseView:
    """Rebuild a close from its record.

    `detail` is a projection, not a permission — it changes how much of the
    answer travels, never what the answer is. Worth saying because every other
    parameter this surface refuses is one that would change what is *allowed*,
    and the distinction is the whole reason this one is safe to offer.
    """
    stream = events(run_id, runs_dir)
    replayed = replay(stream)
    problems = verify_chain(stream) + disagreements(replayed)
    lp = looplib.get(replayed.profile)
    return _view_of(run_id, lp, replayed, stream, problems, detail)


def _view_of(
    run_id: str,
    lp: looplib.Loop,
    replayed: ReplayedClose,
    stream: list[Event],
    problems: list[str],
    detail: Detail = Detail.SUMMARY,
) -> CloseView:
    # The worklist ages an exception against the period it belongs to, which is
    # the loop's, not today's. A wall clock here would make the same close rank
    # differently on a Monday — see the ban on a wall clock inside a decision.
    items = build_worklist(replayed.exceptions, lp.taxonomy(), as_of=lp.period[1])

    by_kind: dict[str, list] = {}
    for event in stream:
        by_kind.setdefault(event.kind.value, []).append(event)

    full = detail is Detail.FULL
    matches = [
        MatchView(
            match_id=e.payload.match_id,
            tier=e.payload.tier,
            anchor_id=e.payload.anchor_id,
            anchor_external=replayed.external_of.get(e.payload.anchor_id, e.payload.anchor_id),
            group_ref=e.payload.group_ref,
            # The ids alone are most of a summary's weight on a 39-row payout and
            # the count is what a reader actually scans. Carried in full at
            # `detail=full`, where the proof they belong to is also here.
            group_ids=list(e.payload.group_ids) if full else [],
            group_size=len(e.payload.group_ids),
            proof=e.payload.proof if full else None,
            proof_id=e.payload.proof_id,
            proof_omitted=""
            if full or e.payload.proof is None
            else f"withheld at detail=summary; fetch it with get_proof({run_id!r}, "
            f"{e.payload.match_id!r}) or ask for detail=full",
        )
        for e in by_kind.get("MatchProven", [])
    ]
    # Counted off the *events*, not off `matches`, and that distinction is a
    # defect this had for one commit: with proofs withheld at `detail=summary`
    # every match read as "unrecorded" and the scorecard's proof-tier split —
    # a headline fact, and the thing that says how much of a close rests on
    # arithmetic rather than on a declaration — quietly became a column of
    # nothing. A projection must never change an answer.
    proof_tiers: dict[str, int] = {}
    declared = 0
    for event in by_kind.get("MatchProven", []):
        proof = event.payload.proof
        key = proof.provenance.value if proof else "unrecorded"
        proof_tiers[key] = proof_tiers.get(key, 0) + 1
        if proof is not None and proof.declared_amount is not None:
            declared += 1

    terminator = by_kind.get("CloseCompleted", [])
    complete = bool(terminator) and terminator[-1].payload.complete

    return CloseView(
        run_id=run_id,
        loop=lp.name,
        policy_ref=replayed.policy_ref,
        policy_digest=replayed.policy_digest,
        period=[d.isoformat() for d in lp.period],
        complete=complete,
        # Only the close-level reasons. An exception queue waiting on a human is
        # the normal state of a real close and must not read as a failed run —
        # that is precisely the distinction "never move silently" rests on.
        blocked=[r for r in replayed.blocked if r not in _signoff_lines(replayed)],
        blocking_exceptions=list(replayed.blocking_exceptions),
        ok=complete and not _hard_blockers(replayed) and not problems,
        tiers=TierSplit(
            matched=len(matches),
            anchors_in_scope=replayed.anchors_in_scope,
            rate=_rate(len(matches), replayed.anchors_in_scope),
            by_match_tier=dict(replayed.tiers),
            by_proof_tier=proof_tiers,
            declared=declared,
        ),
        matches=matches,
        rejected=list(replayed.rejected),
        exceptions=[
            ExceptionView(
                rank=item.rank,
                exception=item.exception,
                code_title=item.code.title,
                code_status=item.code.status,
                owner=item.owner,
                authority_note=item.authority_note,
                cash_impact_paise=item.cash_impact_paise,
                age_days=item.age_days,
            )
            for item in items
        ],
        out_of_scope=dict(replayed.out_of_scope),
        sources=dict(replayed.sources),
        unverified=dict(replayed.unverified),
        postings=len(replayed.postings),
        authority=[e.payload.model_dump(mode="json") for e in by_kind.get("AuthorityVerified", [])],
        rules_applied=[e.payload.model_dump(mode="json") for e in by_kind.get("RuleApplied", [])],
        rules_refused=[
            e.payload.model_dump(mode="json") for e in by_kind.get("ProposalRefused", [])
        ],
        chain_problems=problems,
        unproven_matches=unproven(replayed),
        events=len(stream),
    )


def _signoff_lines(replayed: ReplayedClose) -> set[str]:
    """The one reason line the derivation generates for blocking exceptions.

    Matched by construction rather than by parsing prose: `derive` builds it
    from the count, so this rebuilds the same string from the same count instead
    of pattern-matching English. If the wording moves, this moves with it or the
    property test that closes the loop fails.
    """
    n = len(replayed.blocking_exceptions)
    return {f"{n} exception(s) block sign-off"} if n else set()


def _hard_blockers(replayed: ReplayedClose) -> list[str]:
    return [r for r in replayed.blocked if r not in _signoff_lines(replayed)]


def _rate(numerator: int, denominator: int) -> str:
    """A rate with its own decomposition attached. `bench/rate.py` refuses to
    print one without; there is no reason a surface should be laxer than the
    benchmark."""
    if not denominator:
        return f"{numerator}/unrecorded — the record does not carry a denominator"
    pct = (Decimal(numerator) * 100 / Decimal(denominator)).quantize(Decimal("0.1"))
    return f"{numerator}/{denominator} ({pct}%)"


def proof_of(run_id: str, match_id: str, runs_dir: Path | None = None) -> MatchView:
    """One match with its proof, in full.

    The counterpart to `detail=summary`: a reader opens one row at a time, and
    twenty proofs inlined so that one could be read is how a response reaches
    58 KB.
    """
    for match in view(run_id, runs_dir, detail=Detail.FULL).matches:
        if match.match_id == match_id:
            return match
    raise ServiceError(f"no match {match_id!r} in run {run_id!r}")


def event_page(
    run_id: str, *, offset: int = 0, limit: int | None = None, runs_dir: Path | None = None
) -> Page[dict]:
    """The typed decision log, a budget at a time.

    62 events for a 22-payout month is 114 KB, and this is a toy corpus. The
    page always carries the real total, so a reader can tell "here is the log"
    from "here is the start of the log" — which a bare list could not.
    """
    stream = events(run_id, runs_dir)
    body = [e.model_dump(mode="json") for e in stream]
    return Page[dict](**paginate(body, offset=offset, limit=limit))


def record_page(
    loop_name: str,
    source_set: str,
    *,
    offset: int = 0,
    limit: int | None = None,
    root: Path | None = None,
) -> Page[Record]:
    """The records a loop reads, for a caller who wants ours rather than theirs.

    Worth saying plainly: a verifier should ingest the source files themselves.
    Checking our arithmetic against records we handed over proves the sum, not
    the honesty — and the files, the specs and the policy are all published.
    """
    lp = looplib.get(loop_name)
    base = (root or BATCH_ROOT) / source_set
    missing = lp.missing(base) if base.exists() else list(lp.filenames)
    if missing:
        raise ServiceError(f"{base} is not a complete source set for {lp.name}: {missing} absent")
    loaded = lp.load(base)
    rows = [rec for _, rec in [*loaded.anchor_rows, *loaded.group_rows]]
    rows.sort(key=lambda r: r.record_id)
    page = paginate([r.model_dump(mode="json") for r in rows], offset=offset, limit=limit)
    return Page[Record](**page)


def close(loop_name: str, source_set: str, *, root: Path | None = None, runs_dir=None) -> CloseView:
    """Run one close and return what the record says about it.

    Note what is *not* in the signature: no policy, no tolerance, no rules, no
    chart. A caller chooses which loop and which period, and nothing else. That
    is the whole difference between a surface a model may drive and one it may
    not — audit findings `F1` and `F2` are both "the caller supplied the
    permission", and a parameter is how a caller supplies anything.
    """
    lp = looplib.get(loop_name)
    base = (root or BATCH_ROOT) / source_set
    if not base.exists():
        raise ServiceError(f"no source set {source_set!r} under {root or BATCH_ROOT}")
    try:
        outcome = looplib.run(lp, base, runs_dir=runs_dir, label=source_set)
    except looplib.LoopError as exc:
        raise ServiceError(str(exc)) from exc
    return view(outcome.run_id, runs_dir)


# --------------------------------------------------------------------------
# matching on its own — the stage an external verifier checks
# --------------------------------------------------------------------------


class MatchStageView(BaseModel):
    """What the matcher decided, plus the evidence to check it with.

    The records travel with the proofs on purpose. A verifier that had to ask us
    for the rows would be re-deriving our answer out of our database, which
    proves nothing about whether we are honest — and a verifier holding the
    source files can ignore these and ingest their own, which is what the P13
    gate actually does.
    """

    model_config = ConfigDict(frozen=True)

    api_version: str = API_VERSION
    contract_version: str = CONTRACT_VERSION
    loop: str
    source_set: str
    policy_ref: str
    policy_digest: str
    matches: list[MatchView]
    match_page: dict = Field(default_factory=dict)
    """`total`, `offset`, `returned`, `next_offset` for `matches`.

    The proofs stay inline here rather than being withheld the way a close view
    withholds them, because a verifier calling this is calling it *for* the
    proofs. So the matches page instead — twelve proofs and a cursor, not twenty
    proofs and a context window."""

    rejected: list[str]
    exceptions: list[ReconException]

    records: list[Record] = Field(default_factory=list)
    """Empty unless asked for. 543 rows of a toy corpus is 397 KB — roughly
    100k tokens, most of a model's context, for a batch this size. The count and
    the digest are always here, and `fetch_records` pages them; better still,
    ingest the source files yourself, which is the check that proves something."""

    records_available: int = 0
    records_note: str = ""
    records_digest: str = ""
    source_digests: dict[str, str] = Field(default_factory=dict)


def match(
    loop_name: str,
    source_set: str,
    *,
    root: Path | None = None,
    include_records: bool = False,
    offset: int = 0,
    limit: int | None = None,
) -> MatchStageView:
    """Match and verify one source set. No posting, no ledger, no log.

    `close.match_and_verify` is the stage, unchanged — an arm, a surface and the
    product share one implementation of it rather than three that agree by
    inspection.
    """
    from .close import CloseRequest, match_and_verify
    from .engine import rulestore

    lp = looplib.get(loop_name)
    base = (root or BATCH_ROOT) / source_set
    missing = lp.missing(base) if base.exists() else list(lp.filenames)
    if missing:
        raise ServiceError(f"{base} is not a complete source set for {lp.name}: {missing} absent")

    sources = lp.load(base)
    rules = rulestore.load(lp.profile.name)
    staged = match_and_verify(
        CloseRequest(
            run_id=source_set,
            anchors=sources.anchor_rows,
            groups=sources.group_rows,
            profile=lp.profile,
            policy=lp.policy(),
            taxonomy=lp.taxonomy(),
            chart=lp.chart(),
            period=lp.period,
            opened_on=lp.opened_on,
            journal_path=Path("/dev/null"),
            source_proofs=sources.proofs,
            provenance=sources.provenance,
            out_of_scope=sources.scope,
            rules=rules,
        )
    )
    records = sorted(staged.records.values(), key=lambda r: r.record_id)
    proven = [
        MatchView(
            match_id=m.match_id,
            tier=m.tier.value,
            anchor_id=m.anchor_id,
            anchor_external=staged.external_of.get(m.anchor_id, m.anchor_id),
            group_ref=m.group_ref,
            group_ids=list(m.group_ids),
            group_size=len(m.group_ids),
            proof=m.proof,
            proof_id=m.proof.proof_id,
        )
        for m in staged.matches
    ]
    page = paginate([mv.model_dump(mode="json") for mv in proven], offset=offset, limit=limit)
    shown = {row["match_id"] for row in page["items"]}
    return MatchStageView(
        loop=lp.name,
        source_set=source_set,
        policy_ref=lp.policy().ref,
        policy_digest=looplib.file_digest(lp.policy_file),
        matches=[mv for mv in proven if mv.match_id in shown],
        match_page={k: v for k, v in page.items() if k != "items"},
        rejected=list(staged.refuted),
        exceptions=list(staged.exceptions),
        records=records if include_records else [],
        records_available=len(records),
        records_note=""
        if include_records
        else (
            f"{len(records)} record(s) withheld — they are ~{_kb(records)} KB and this "
            f"response goes into a context window. Page them with fetch_records, or "
            f"ingest the source files yourself with the published adapter spec, which "
            f"is the check worth making: verifying our arithmetic against records we "
            f"handed you proves the sum, not the honesty."
        ),
        records_digest=records_digest(records),
        source_digests=dict(sources.digests),
    )


def _kb(records: list[Record]) -> int:
    return max(1, len(json.dumps([r.model_dump(mode="json") for r in records])) // 1024)


def records_digest(records: list[Record]) -> str:
    """One id for a set of records, so a verifier can say which evidence it
    used. Order-independent by construction — a digest that moved when the
    source reordered its file would report a difference that is not one."""
    body = sorted(
        f"{r.record_id}|{r.side}|{r.amount}|{r.currency}|{r.posted_on.isoformat()}" for r in records
    )
    return hashlib.sha256("\n".join(body).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# the stateless public verification — the trust argument, as a function call
# --------------------------------------------------------------------------


class Verification(BaseModel):
    """A verdict, and whose constraints produced it.

    `proven` alone would be a laundering channel: a caller supplies a lenient
    policy of their own, gets `true`, and quotes it as though the system had
    said so. So the verdict always carries the policy that judged it and where
    that policy came from. `policy_source == "in-force"` means we loaded it from
    the loop's signed bundle; `"caller-supplied"` means the caller brought it and
    the verdict is about *their* constraints, which is exactly right when the
    caller is an auditor and exactly not a statement by us.
    """

    model_config = ConfigDict(frozen=True)

    api_version: str = API_VERSION
    contract_version: str = CONTRACT_VERSION
    proven: bool
    proof_id: str
    recomputed_residual: Decimal | None
    reasons: list[str] = Field(default_factory=list)
    policy_ref: str | None = None
    policy_source: str = ""
    records_digest: str = ""
    records_supplied: int = 0


def check(
    proof: Proof,
    records: list[Record],
    *,
    policy: Policy | None = None,
    loop_name: str | None = None,
    rules: list | None = None,
    declared_scope: list[str] | None = None,
) -> Verification:
    """Re-derive one proof from records the caller holds. Stateless.

    Nothing is read from disk except a named loop's published policy, and
    nothing is remembered. Hand it a proof from our decision log and records you
    ingested yourself from the source files, and it tells you whether our
    arithmetic holds — with no account, no database and no reason to trust us.
    That is the property the whole design is for, and it is a function call.

    Exactly one of `policy` or `loop_name` must be given. There is no default:
    a verification that silently picked a policy would be deciding the
    constraints on the caller's behalf, and every audit finding in
    `docs/04-CONTROL-PLANE-AUDIT.md` is a version of that mistake.
    """
    if (policy is None) == (loop_name is None):
        raise ServiceError(
            "name a loop whose published policy to verify under, or supply a "
            "policy; not both and not neither. A default policy would be this "
            "function choosing the constraints on the caller's behalf"
        )
    source = "caller-supplied"
    if loop_name is not None:
        policy = looplib.get(loop_name).policy()
        source = "in-force"

    by_id = {r.record_id: r for r in records}
    verdict = verify_proof(
        proof,
        by_id,
        policy,
        bundle=rules or [],
        declared_scope=declared_scope or [],
    )
    return Verification(
        proven=verdict.proven,
        proof_id=proof.proof_id,
        recomputed_residual=verdict.recomputed_residual,
        reasons=list(verdict.reasons),
        policy_ref=verdict.policy_ref,
        policy_source=source,
        records_digest=records_digest(records),
        records_supplied=len(records),
    )


class ChainVerification(BaseModel):
    """Whether a decision log vouches for itself.

    Public and stateless for the same reason `check` is: an auditor holding a
    year-old `decisions.jsonl` can confirm nothing in it moved, without us. What
    it does *not* prove is custody — an actor who can rewrite the whole file can
    recompute the chain over anything. `recon.journal` says so at length and
    this repeats it rather than letting a green tick overclaim.
    """

    model_config = ConfigDict(frozen=True)

    holds: bool
    events: int
    terminated: bool
    problems: list[str] = Field(default_factory=list)
    caveat: str = (
        "A hash chain proves internal consistency, not custody. Someone able to "
        "rewrite the whole file can recompute the chain over anything they like; "
        "what this closes is the partial edit and the truncated tail."
    )


def check_chain(stream: list[Event]) -> ChainVerification:
    problems = verify_chain(stream) + disagreements(replay(stream))
    return ChainVerification(
        holds=not problems,
        events=len(stream),
        terminated=bool(stream) and stream[-1].kind.value == "CloseCompleted",
        problems=problems,
    )


class SourceCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    spec_id: str
    recorded_hash: str
    actual_hash: str
    same_file: bool


class Reverification(BaseModel):
    """A close re-derived from the files on disk and the proofs in its record.

    This is the P13 claim performed by the system on itself, and it is the same
    call an outsider makes: nothing is read from the memory of the process that
    ran the close. The sources are re-ingested with the published adapter specs,
    each document's sha256 is checked against the hash the record pinned, and
    every proof in the log is re-derived against those fresh records under the
    policy in force.

    It can fail in three interestingly different ways, so they are reported
    separately rather than as one boolean. `same_file` false means you pointed
    it at different bytes than the close ran on — a mistake, not a finding.
    `refuted` means the arithmetic does not hold: that is a finding about us.
    `missing_proofs` means the record does not contain a proof to check, which
    is neither — it is a gap in the evidence, and it must not read as a pass.
    """

    model_config = ConfigDict(frozen=True)

    api_version: str = API_VERSION
    contract_version: str = CONTRACT_VERSION
    run_id: str
    loop: str
    source_set: str
    policy_ref: str
    sources: list[SourceCheck]
    sources_match: bool
    records_ingested: int
    records_digest: str
    proofs_checked: int
    proven: int
    refuted: list[dict] = Field(default_factory=list)
    missing_proofs: list[str] = Field(default_factory=list)
    holds: bool


def source_set_of(run_id: str, runs_dir: Path | None = None, *, root: Path | None = None) -> str:
    """Which period's files this close actually ran on, by digest.

    The record pins a sha256 per source, so this is a fact rather than a guess
    from the run id's label. It exists because the surface was offering
    "re-derive against B" for a close that ran on A, and getting back twenty
    refutations that mean nothing: record ids are content-derived, so B's files
    produce different ids and every proof cites rows that are not there. The
    engine was right and the page was misleading, which is the worse of the two.

    Empty string when no available set matches — including when the files have
    been replaced since, which is itself worth showing.
    """
    replayed = replay(events(run_id, runs_dir))
    lp = looplib.get(replayed.profile)
    base = root or BATCH_ROOT
    if not base.exists():
        return ""
    for directory in sorted(d for d in base.iterdir() if d.is_dir()):
        if lp.missing(directory):
            continue
        try:
            digests = lp.load(directory).digests
        except Exception:  # an unreadable set is not the one we are looking for
            continue
        if digests == replayed.source_digests:
            return directory.name
    return ""


def reverify(
    run_id: str, source_set: str, *, root: Path | None = None, runs_dir: Path | None = None
) -> Reverification:
    """Re-ingest the sources, re-derive every proof the record contains.

    Deliberately routed through `check` — the same stateless verification an
    external caller gets — rather than through a private path. A re-derivation
    that used an internal shortcut would be measuring the shortcut.
    """
    stream = events(run_id, runs_dir)
    replayed = replay(stream)
    lp = looplib.get(replayed.profile)
    base = (root or BATCH_ROOT) / source_set
    missing_files = lp.missing(base) if base.exists() else list(lp.filenames)
    if missing_files:
        raise ServiceError(
            f"{base} is not a complete source set for {lp.name}: {missing_files} absent"
        )

    loaded = lp.load(base)
    spec_of = _specs_by_source(lp)
    checks = [
        SourceCheck(
            source=source,
            spec_id=spec_of.get(source, ""),
            recorded_hash=replayed.source_digests.get(source, ""),
            actual_hash=actual,
            same_file=replayed.source_digests.get(source, "") == actual,
        )
        for source, actual in sorted(loaded.digests.items())
    ]
    records = [rec for _, rec in [*loaded.anchor_rows, *loaded.group_rows]]

    proven = 0
    refuted: list[dict] = []
    for match_id, proof_id in sorted(replayed.match_proofs.items()):
        proof = replayed.proofs.get(proof_id)
        if proof is None:
            continue
        result = check(
            proof,
            records,
            loop_name=lp.name,
            declared_scope=list(replayed.out_of_scope),
        )
        if result.proven:
            proven += 1
        else:
            refuted.append({"match_id": match_id, "proof_id": proof_id, "reasons": result.reasons})

    gaps = unproven(replayed)
    checked = proven + len(refuted)
    return Reverification(
        run_id=run_id,
        loop=lp.name,
        source_set=source_set,
        policy_ref=lp.policy().ref,
        sources=checks,
        sources_match=all(c.same_file for c in checks),
        records_ingested=len(records),
        records_digest=records_digest(records),
        proofs_checked=checked,
        proven=proven,
        refuted=refuted,
        missing_proofs=gaps,
        # Every one of the three has to hold. A run with no proofs in its record
        # would otherwise pass with `0 checked, 0 refuted` — the unmeasured
        # thing reported as a clean result, which is the failure this codebase
        # keeps rediscovering.
        holds=all(c.same_file for c in checks) and not refuted and not gaps and checked > 0,
    )


# --------------------------------------------------------------------------
# the audit export — every decision with its proof, its rule and its approver
# --------------------------------------------------------------------------


class AuditBundle(BaseModel):
    """Everything needed to re-derive a close, and nothing that requires us.

    Deliberately self-contained: the proofs, the source document hashes, the
    adapter spec ids that read them, the policy that judged them and the
    signature verdicts on the authority. An auditor ingests the same files with
    the same published specs, calls `check` on each proof, and either reaches
    our numbers or does not.
    """

    model_config = ConfigDict(frozen=True)

    api_version: str = API_VERSION
    contract_version: str = CONTRACT_VERSION
    run_id: str
    loop: str
    policy_ref: str | None
    policy_digest: str
    policy_approved_by: str
    taxonomy_ref: str
    period: list[str]
    sources: list[dict]
    authority: list[dict]
    decisions: list[dict]
    decision_page: dict
    """`total`, `offset`, `returned`, `next_offset` for `decisions` above.

    The bundle is meant to be complete, so paging it is a real cost and is
    stated rather than hidden: a reader who stops at page one has part of an
    audit, and the envelope is what tells them so. `GET /v1/runs/{id}/export`
    with an explicit `limit` returns the lot for an actual download."""

    exceptions: list[dict]
    out_of_scope: dict[str, str]
    postings: list[dict]
    terminator: dict
    chain: ChainVerification
    unproven_matches: list[str]
    how_to_verify: list[str]


def audit(
    run_id: str,
    runs_dir: Path | None = None,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> AuditBundle:
    stream = events(run_id, runs_dir)
    replayed = replay(stream)
    lp = looplib.get(replayed.profile)
    pol = lp.policy()

    by_kind: dict[str, list] = {}
    for event in stream:
        by_kind.setdefault(event.kind.value, []).append(event)

    spec_of = _specs_by_source(lp)
    sources = []
    for e in by_kind.get("SourceIngested", []) + by_kind.get("IntakeUnverified", []):
        p = e.payload
        sources.append(
            {
                "source": p.source,
                "spec_id": spec_of.get(p.source, ""),
                "doc_hash": p.doc_hash,
                "strength": p.strength,
                "rows_in_file": p.rows_in_file,
                "rows_parsed": p.rows_parsed,
                "rows_rejected": p.rows_rejected,
                "gap": getattr(p, "gap", ""),
            }
        )

    decisions = []
    for e in by_kind.get("MatchProven", []):
        p = e.payload
        proof = p.proof
        decisions.append(
            {
                "kind": "match",
                "match_id": p.match_id,
                "match_tier": p.tier,
                "proof_id": p.proof_id,
                "proof_tier": proof.provenance.value if proof else "unrecorded",
                "rule": f"{proof.rule_id}@v{proof.rule_version}"
                if proof and proof.rule_id
                else None,
                "rule_bundle_digest": proof.rule_bundle_digest if proof else None,
                "attested_by": proof.attested_by if proof else None,
                "declared_gap": proof.declared_gap if proof else None,
                "declared_amount": str(proof.declared_amount)
                if proof and proof.declared_amount is not None
                else None,
                "entry_id": proof.entry_id if proof else None,
                "at": e.at.isoformat(),
                "policy_ref": e.policy_ref,
                "proof": proof.model_dump(mode="json") if proof else None,
            }
        )
    for e in by_kind.get("MatchRejected", []):
        p = e.payload
        decisions.append(
            {
                "kind": "match_rejected",
                "match_id": p.match_id,
                "proof_id": p.proof_id,
                "reasons": list(p.reasons),
                "at": e.at.isoformat(),
                "policy_ref": e.policy_ref,
            }
        )
    for e in by_kind.get("RuleApplied", []):
        decisions.append(
            {"kind": "rule_applied", "at": e.at.isoformat(), **e.payload.model_dump(mode="json")}
        )
    for e in by_kind.get("ProposalRefused", []):
        decisions.append(
            {"kind": "rule_refused", "at": e.at.isoformat(), **e.payload.model_dump(mode="json")}
        )

    decisions.sort(key=lambda d: (d["at"], d.get("match_id") or d.get("rule_ref") or ""))
    page = paginate(decisions, offset=offset, limit=limit)
    terminator = by_kind.get("CloseCompleted", [])
    return AuditBundle(
        run_id=run_id,
        loop=lp.name,
        policy_ref=replayed.policy_ref,
        policy_digest=replayed.policy_digest,
        policy_approved_by=pol.approved_by,
        taxonomy_ref=lp.taxonomy().ref,
        period=[d.isoformat() for d in lp.period],
        sources=sources,
        authority=[e.payload.model_dump(mode="json") for e in by_kind.get("AuthorityVerified", [])],
        decisions=page.pop("items"),
        decision_page=page,
        exceptions=[e.payload.model_dump(mode="json") for e in by_kind.get("ExceptionRaised", [])],
        out_of_scope=dict(replayed.out_of_scope),
        postings=[e.payload.model_dump(mode="json") for e in by_kind.get("PostingWritten", [])],
        terminator=terminator[-1].payload.model_dump(mode="json") if terminator else {},
        chain=check_chain(stream),
        unproven_matches=unproven(replayed),
        how_to_verify=[
            "1. Fetch the source files named in `sources` and confirm each sha256 "
            "matches its `doc_hash`.",
            f"2. Ingest them with the published adapter spec named in `spec_id` "
            f"(`data/adapters/<spec_id>.json`) over the period {lp.period[0]}..{lp.period[1]}.",
            f"3. For each entry in `decisions` with kind=match, call verify_proof "
            f"with its `proof`, your own records, and policy {pol.ref}.",
            "4. Confirm `chain.holds` over the decision log itself.",
            "None of this requires our database, our network or our goodwill. A "
            "step that disagrees is a finding about us, not about your copy.",
        ],
    )


# --------------------------------------------------------------------------
# the one thing a proposer may do — propose, and be told whether it would hold
# --------------------------------------------------------------------------


class ProposalVerdict(BaseModel):
    """Whether a reclassification would be admissible. Nothing is persisted.

    The model never writes to the ledger (CLAUDE.md rule 2), and this is where
    that rule meets an interface a model actually drives. The tool runs the
    proposal through `triage.classify.check_proposal` — the same checker the
    live triage path uses — and returns the verdict. It does not change what the
    close decided, and `test_a_proposal_changes_nothing` re-reads the close
    afterwards to prove it.

    `persisted` is always false and is in the response on purpose. A proposal
    store needs cross-close state this build does not have; saying so beats a
    field that quietly means nothing.
    """

    model_config = ConfigDict(frozen=True)

    admissible: bool
    reasons: list[str] = Field(default_factory=list)
    exception_id: str
    proposed_code: str
    current_code: str = ""
    current_provenance: str = ""
    best_tier_a_proposal_can_carry: str = "P2"
    persisted: bool = False
    persistence_note: str = (
        "Not stored. A proposal outlives the close it speaks about, and this "
        "build has no cross-close store — see STATUS.md. An attestation is a "
        "separate decision by a named human and is not reachable from here."
    )


def propose_reclassification(
    run_id: str,
    exception_id: str,
    code: str,
    hypothesis: str,
    evidence: list[str],
    *,
    runs_dir: Path | None = None,
) -> ProposalVerdict:
    """Check a proposed code against the exception and the registry."""
    stream = events(run_id, runs_dir)
    replayed = replay(stream)
    lp = looplib.get(replayed.profile)
    by_id = {e.exception_id: e for e in replayed.exceptions}
    subject: ReconException | None = by_id.get(exception_id)

    verdict = check_proposal(
        {
            "exception_id": exception_id,
            "code": code,
            "hypothesis": hypothesis,
            "evidence": list(evidence),
        },
        exceptions=by_id,
        taxonomy=lp.taxonomy(),
    )
    return ProposalVerdict(
        admissible=verdict.ok,
        reasons=list(verdict.reasons),
        exception_id=exception_id,
        proposed_code=code,
        current_code=subject.code if subject else "",
        current_provenance=subject.code_provenance.value if subject else "",
    )


# --------------------------------------------------------------------------
# the authority in force, and the vocabulary
# --------------------------------------------------------------------------


class AuthorityView(BaseModel):
    """Which policy, vocabulary and rules govern a loop — and who signed them."""

    model_config = ConfigDict(frozen=True)

    api_version: str = API_VERSION
    contract_version: str = CONTRACT_VERSION
    loop: str
    policy: Policy
    taxonomy_ref: str
    codes: list[dict]
    rules: list[dict]
    bundles: list[dict]


def authority(loop_name: str) -> AuthorityView:
    from .engine import rulestore

    lp = looplib.get(loop_name)
    tax: TaxonomyRegistry = lp.taxonomy()
    return AuthorityView(
        loop=lp.name,
        policy=lp.policy(),
        taxonomy_ref=tax.ref,
        codes=[
            {
                "code": c.code,
                "title": c.title,
                "status": c.status.value,
                "owner": c.owner,
                "may_direct_a_posting": c.status is CodeStatus.PROMOTED,
                "escalation_is_correct": c.escalation_is_correct,
                "authority": c.authority.summary(),
            }
            for c in sorted(tax.codes.values(), key=lambda c: c.code)
        ],
        rules=[
            {
                "rule_id": r.rule_id,
                "ref": r.ref,
                "status": r.status.value,
                "then": [a.kind.value for a in r.then],
                "approved_by": getattr(r.promotion, "approved_by", None) if r.promotion else None,
                "policy_ref": getattr(r.promotion, "policy_ref", None) if r.promotion else None,
            }
            for r in rulestore.load(lp.profile.name)
        ],
        bundles=[_bundle(b) for b in lp.bundles()],
    )


def _specs_by_source(lp: looplib.Loop) -> dict[str, str]:
    """source name -> the adapter spec id that produced it.

    Built from the specs rather than assumed equal to them. They happen to
    coincide for this loop, and a map that is right by coincidence is one an
    audit export quietly gets wrong the first time a spec is renamed — the
    export would then tell an auditor to re-ingest with a spec that does not
    exist, which is worse than telling them nothing.
    """
    from .intake import load_spec

    return {load_spec(b.spec_id).source: b.spec_id for b in lp.sources}


def _bundle(path: Path) -> dict:
    verdict = trust.verify(path)
    return {
        "bundle": verdict.name,
        "digest": verdict.digest,
        "signed": verdict.signed,
        "trusted": verdict.trusted,
        "signed_by": verdict.signed_by,
        "key_id": verdict.key_id,
        "reasons": list(verdict.reasons),
    }


def contracts() -> dict:
    """The semver'd public shapes, as JSON Schema.

    Published because ADR-002's argument is compoundability — other systems
    build on these — and a shape nobody can fetch is a shape nobody can build
    on. The schemas come from the models themselves, so they cannot drift from
    what the wire actually carries.
    """
    from .contracts.adapter import AdapterSpec
    from .contracts.rule import Rule

    models = {
        "Record": Record,
        "Proof": Proof,
        "ReconException": ReconException,
        "Policy": Policy,
        "Rule": Rule,
        "AdapterSpec": AdapterSpec,
        "Event": Event,
    }
    return {
        "contract_version": CONTRACT_VERSION,
        "api_version": API_VERSION,
        "adr": "ADR-002 — these are semver'd public objects. A field change is a "
        "version bump, not an edit.",
        "schemas": {name: model.model_json_schema() for name, model in models.items()},
    }
