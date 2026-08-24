"""Ablation runner — the measurement, one command.

    python -m bench.run              # batches A and B, four arms, eight metrics
    python -m bench.run --batch A

Three things this does that a printing script does not.

**It verifies its inputs before measuring them.** `data/batches/` is gitignored
and `MANIFEST.json` is not, so a clean checkout has hashes and no data. The
runner regenerates from the seed and then re-hashes against the committed
manifest. A number computed over unverified bytes is a number about an unknown
file.

**Nothing is filtered before the accountability boundary.** Everything the
sources produced is handed to the engine; what the loop does not reconcile is
declared out of scope *with a reason* and printed. Until P10 this runner cut the
bank side down to gateway credits before the completeness audit could see it,
and the planted `E08` — a credit with nothing behind it, the most interesting
line on a statement — left the pipeline with no disposition while invariant 8
still read `complete`.

**Absence is not zero.** The LLM arm is named on every run and reports absent.
"""

from __future__ import annotations

import argparse
import hashlib
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from recon.contracts import (
    PRODUCERS,
    CloseCompletedPayload,
    EventKind,
    Policy,
    ProofTier,
    ReconException,
    Record,
    TaxonomyRegistry,
)
from recon.engine.blocking import BlockingPolicy, CandidateSet, RecallReport, recall
from recon.engine.blocking import build as build_candidates
from recon.engine.completeness import CompletenessReport
from recon.engine.tiers import MatchProfile
from recon.engine.tolerance import TolerancePolicy
from recon.intake import ingest, load_spec
from recon.journal import Journal
from recon.journal.derive import Decisions, derive
from recon.ledger.accounts import SETTLEMENT_CHART
from recon.ledger.beancount_io import CloseResult as LedgerResult
from recon.ledger.beancount_io import JournalEntry, post_and_assert
from recon.ledger.posting_rules import entries_for
from recon.triage.worklist import WorkItem, summarise
from recon.triage.worklist import build as build_worklist

from .arms import deterministic, llm_only, securo_baseline
from .metrics import (
    EIGHT_METRICS,
    Scorecard,
    render_table,
    score,
    scorecard_digest,
    truth_groups,
    truth_pairs,
)
from .planted import load_planted, score_planted

BATCHES = Path("data/batches")
POLICY_DIR = Path("data/policy")
POLICY_FILE = POLICY_DIR / "settlement_3way.json"
TAXONOMY_FILE = Path("data/taxonomy/codes.json")
RUNS = Path("data/runs")
#: Authority, loaded from disk like an adapter spec so a change shows in a diff.
SETTLEMENT_POLICY = Policy.model_validate_json(POLICY_FILE.read_text(encoding="utf-8"))
#: The vocabulary, loaded like the policy — a separate versioned input, not
#: something the thing being judged gets to supply.
TAXONOMY = TaxonomyRegistry.model_validate_json(TAXONOMY_FILE.read_text(encoding="utf-8"))
WINDOW = (date(2026, 7, 1), date(2026, 10, 31))

#: Which planted defects this loop is able to see. The bank<->settlement leg is
#: what runs; the order register is a third leg that lands with the second
#: profile. Read by the planted scorer so a defect on a leg we do not run is
#: reported separately instead of counted as a miss — the same attribution split
#: as blocking's `dropped` vs `unreachable` at P4, and, like that one, not an
#: escape hatch: what is in scope comes from the P0 label, never from the run.
IN_SCOPE_LEGS = {"bank"}

SETTLEMENT_3WAY = MatchProfile(
    name="settlement_3way",
    anchor_side="bank",
    group_side="settlement",
    # A bank credit and the settlement rows behind it are the same money seen
    # from two sides, so the group side is negated for the residual to close.
    side_signs={"bank": 1, "settlement": -1},
    tolerance=TolerancePolicy(absolute=Decimal("0.50"), date_window_days=3),
    counterparty_key="gateway",
    # A fee shares its charge's payment_id; without this the solver reports
    # subsets that mix a charge from one group with a fee from another.
    cohesion_key="payment_id",
)


@dataclass(frozen=True)
class Sides:
    bank: list[tuple[str, Record]]
    settlement: list[tuple[str, Record]]
    provenance: ProofTier
    scope: dict[str, str]
    """record id -> why this loop does not reconcile it. Never a bare drop."""

    proofs: list = field(default_factory=list)
    """The intake proof per source. Carried so the record can say what each
    source was worth, rather than the close asserting it second-hand."""

    digests: dict[str, str] = field(default_factory=dict)
    strengths: dict[str, str] = field(default_factory=dict)

    @property
    def anchors(self) -> list[tuple[str, Record]]:
        """The bank side this loop actually reconciles. `bank` keeps everything
        so the completeness audit sees the whole statement; this is the subset
        the tiers are offered."""
        return [(ext, rec) for ext, rec in self.bank if rec.record_id not in self.scope]

    def in_scope(self) -> tuple[list[tuple[str, Record]], list[tuple[str, Record]], ProofTier]:
        """Anchors, group rows, weakest provenance — the three things a caller
        that only wants to match needs."""
        return self.anchors, self.settlement, self.provenance


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class CloseResult:
    batch: str
    cards: list[Scorecard] = field(default_factory=list)
    blocking: RecallReport | None = None
    candidates: CandidateSet | None = None
    completeness: CompletenessReport | None = None
    exceptions: list[ReconException] = field(default_factory=list)
    bank_records: list[Record] = field(default_factory=list)
    settlement_records: list[Record] = field(default_factory=list)
    external_of: dict[str, str] = field(default_factory=dict)
    scope: dict[str, str] = field(default_factory=dict)
    records: dict[str, Record] = field(default_factory=dict)
    matches: list = field(default_factory=list)
    entries: list[JournalEntry] = field(default_factory=list)
    not_posted: list[str] = field(default_factory=list)
    taxonomy: TaxonomyRegistry | None = None
    worklist: list[WorkItem] = field(default_factory=list)
    ledger: LedgerResult | None = None
    journal_path: Path | None = None
    decisions: Decisions | None = None
    unproduced_kinds: dict[str, str] = field(default_factory=dict)
    ok: bool = True


def load_sides(batch: str) -> Sides:
    """Bank comes from the CAMT rendering because it carries NtryRef, which is
    the id the labels use. The CSV is the same account and ingests identically
    (proved at P2); using the CAMT here keeps scoring traceable to ground truth
    without a second id mapping to get wrong.

    Every ingested record is returned. The settlement loop reconciles money
    coming *in*, so debits are declared out of scope with a reason and travel
    to the completeness audit rather than being filtered away. A credit is in
    scope whether or not it looks like a gateway payout: a receipt nobody can
    attribute is the case a controller most wants raised, and recognising it by
    the very key it is missing would drop it.
    """
    root = BATCHES / batch
    bank_result = ingest(
        load_spec("icici-camt"), root / "bank_icici_camt053.xml", WINDOW, SETTLEMENT_POLICY
    )
    settle_result = ingest(
        load_spec("gateway-settlement"), root / "settlement.csv", WINDOW, SETTLEMENT_POLICY
    )

    bank = [(rec.keys["entry_ref"], rec) for rec in bank_result.records]
    settlement = [(rec.source_row_id, rec) for rec in settle_result.records if rec.source_row_id]

    scope = {
        rec.record_id: (
            "debit — the settlement loop reconciles receipts; outgoing payments "
            "belong to the AP and payroll loops"
        )
        for _, rec in bank
        if rec.amount <= 0
    }

    weakest = min(
        (bank_result.proof.provenance, settle_result.proof.provenance),
        key=lambda t: 0 if t is ProofTier.P0_ARITHMETIC else 1,
    )
    proofs = [bank_result.proof, settle_result.proof]
    return Sides(
        bank=bank,
        settlement=settlement,
        provenance=weakest,
        scope=scope,
        proofs=proofs,
        digests={p.source: p.doc_hash for p in proofs},
        strengths={p.source: p.strength for p in proofs},
    )


def close(batch: str, journal_dir: Path | None = None) -> CloseResult:
    """One close: matched, posted, recorded, scored.

    The order matters. Posting happens before the log is derived, because a
    decision log for a reconciliation that never reached the books is a log of
    half the system. Deriving happens before scoring, because `derive` refuses
    to finish while any input the audit disposed of is named by no event — so a
    scorecard cannot be produced over a run the record does not account for.
    """
    sides = load_sides(batch)
    labels = BATCHES / batch / "labels.json"
    truth = truth_pairs(labels)

    anchors = [rec for _, rec in sides.anchors]
    group_records = [rec for _, rec in sides.settlement]
    candidates = build_candidates(anchors, group_records, BlockingPolicy())
    blocking = recall(
        candidates,
        truth_groups(labels),
        {ext: rec.record_id for ext, rec in sides.bank},
        declared_groups={rec.group_ref for rec in group_records if rec.group_ref},
    )

    external_of = {rec.record_id: ext for ext, rec in sides.bank + sides.settlement}
    planted = load_planted(labels, external_of)
    records_scored = len(anchors) + len(group_records)

    def timed(fn, *args, **kwargs):
        started = time.perf_counter_ns()
        result = fn(*args, **kwargs)
        return result, time.perf_counter_ns() - started

    raw, raw_ns = timed(securo_baseline.run_raw, sides.anchors, sides.settlement)
    grouped, grouped_ns = timed(securo_baseline.run_grouped, sides.anchors, sides.settlement)
    ours, ours_ns = timed(
        deterministic.run,
        sides.bank,
        sides.settlement,
        SETTLEMENT_3WAY,
        SETTLEMENT_POLICY,
        sides.provenance,
        candidates,
        sides.scope,
    )

    cards = [
        score(
            result,
            truth,
            exceptions=score_planted(planted, result.exceptions, in_scope_legs=IN_SCOPE_LEGS),
            elapsed_ns=elapsed,
            records_scored=records_scored,
        )
        for result, elapsed in ((raw, raw_ns), (grouped, grouped_ns), (ours, ours_ns))
    ]
    cards.append(score(llm_only.absent(), truth))

    # --- the books -------------------------------------------------------
    records = {rec.record_id: rec for _, rec in sides.bank + sides.settlement}
    entries, not_posted = entries_for(
        matches=ours.matches,
        exceptions=list(ours.exceptions),
        records=records,
        anchor_side=SETTLEMENT_3WAY.anchor_side,
        taxonomy=TAXONOMY,
    )
    ledger = post_and_assert(
        entries,
        SETTLEMENT_CHART,
        opened_on=date(2026, 7, 1),
        period_end=WINDOW[1],
        policy=SETTLEMENT_POLICY,
    )

    # Extended, not recomputed. The engine's audit already did the set
    # arithmetic over records; the postings and the intake strengths are what it
    # could not know. Auditing twice would leave two answers to the same
    # question, and the one nobody reads is the one that rots.
    completeness = ours.completeness.extend(
        sources=sides.strengths,
        proof_ids=[m.proof.proof_id for m in ours.matches],
        posted_proof_ids=[e.proof_id for e in entries if e.proof_id],
    )

    # --- the queue a human actually works --------------------------------
    # Built before the record so an unresolvable code stops the run here rather
    # than being written into a log as if it were a finding.
    worklist = build_worklist(list(ours.exceptions), TAXONOMY, as_of=WINDOW[1])

    # --- the record ------------------------------------------------------
    decisions = Decisions(
        batch=batch,
        profile=SETTLEMENT_3WAY.name,
        policy=SETTLEMENT_POLICY,
        policy_digest=_digest(POLICY_FILE),
        taxonomy=TAXONOMY,
        taxonomy_digest=_digest(TAXONOMY_FILE),
        source_digests=sides.digests,
        sources=sides.proofs,
        scope=sides.scope,
        matches=list(ours.matches),
        rejected=list(ours.rejected),
        exceptions=list(ours.exceptions),
        entries=entries,
        completeness=completeness,
        records=records,
        external_of=external_of,
        blocked_reasons=[f"{e.kind}: {e.message}" for e in ledger.errors],
        label_digest=_digest(labels),
        period=[WINDOW[0].isoformat(), WINDOW[1].isoformat()],
    )
    journal = Journal((journal_dir or RUNS) / batch / "decisions.jsonl", fresh=True)
    journal.extend(derive(decisions))

    complete = completeness.complete
    card = {c.arm: c for c in cards}["deterministic"]
    journal.append(
        EventKind.CLOSE_COMPLETED,
        actor="engine",
        outcome="complete" if complete else "incomplete",
        input_hash=decisions.label_digest,
        policy_ref=SETTLEMENT_POLICY.ref,
        payload=CloseCompletedPayload(
            events_before_this=journal.count,
            matches=card.produced,
            rejected=len(ours.rejected),
            exceptions=len(ours.exceptions),
            postings=len(entries),
            out_of_scope=len(sides.scope),
            scorecard_digest=scorecard_digest(card),
            complete=complete,
        ),
    )

    return CloseResult(
        batch=batch,
        cards=cards,
        blocking=blocking,
        candidates=candidates,
        completeness=completeness,
        exceptions=list(ours.exceptions),
        bank_records=[rec for _, rec in sides.bank],
        settlement_records=group_records,
        external_of=external_of,
        scope=sides.scope,
        records=records,
        matches=list(ours.matches),
        entries=entries,
        not_posted=not_posted,
        ledger=ledger,
        taxonomy=TAXONOMY,
        worklist=worklist,
        journal_path=journal.path,
        decisions=decisions,
        unproduced_kinds={k.value: v for k, v in PRODUCERS.items() if v.startswith("P")},
        ok=not blocking.dropped and complete and not ledger.blocked,
    )


def render(result: CloseResult) -> str:
    """The page. Blocking recall sits above the match rates because a dropped
    true pair caps everything below it (invariant 6), and the exception table
    sits below them because that is where the baseline stops tying."""
    lines = [
        f"batch {result.batch}  ·  "
        f"{len(result.bank_records) - len(result.scope)} bank credits in scope  ·  "
        f"{len(result.settlement_records)} settlement rows  ·  "
        f"{len(result.scope)} out of scope",
    ]
    reasons = sorted(set(result.scope.values()))
    lines += [f"  out of scope: {r}" for r in reasons]
    lines.append(f"true pairs (payouts banked in period): {result.cards[0].true_pairs}")
    if result.candidates is not None:
        lines.append(f"blocking: {result.candidates.summary()}")
    if result.blocking is not None:
        lines.append(f"          {result.blocking.render()}")
    lines += ["", render_table(result.cards)]

    if result.completeness is not None:
        lines += ["", result.completeness.render()]

    card = {c.arm: c for c in result.cards}["deterministic"]
    if card.exceptions is not None:
        lines += ["", "planted defects, one line each (labels authored at P0):"]
        lines += [f"  {line}" for line in card.exceptions.detail]
        lines.append(f"  {card.cost_line()}")

    if result.ledger is not None:
        lines += [
            "",
            f"journal: {len(result.entries)} entries, "
            f"{'BLOCKED' if result.ledger.blocked else 'balanced'}, "
            f"{result.ledger.entries_loaded} loaded by beancount",
        ]
        lines += [f"  not posted: {reason}" for reason in result.not_posted]

    if result.journal_path is not None:
        lines.append(
            f"record: {result.journal_path} — replay with "
            f"`python -m bench.replay_cli {result.batch}`"
        )
        if result.unproduced_kinds:
            lines.append(
                "  event kinds with no producer yet: "
                + ", ".join(f"{k} ({v.split(' ')[0]})" for k, v in result.unproduced_kinds.items())
            )

    if result.worklist:
        # The tail is the product, so the queue a human works is on the page —
        # ranked, routed, and showing which codes nobody has ratified yet.
        lines += [
            "",
            f"worklist ({result.taxonomy.ref}, {len(result.worklist)} items, "
            f"ranked by cash impact x age):",
        ]
        lines += [f"  {item.render()}" for item in result.worklist]
        lines.append(f"  {summarise(result.worklist)}")

    if result.exceptions:
        lines.append("\nexceptions raised (deterministic arm):")
        for exc in result.exceptions:
            lines.append(f"  {exc.code}  ₹{exc.amount:>12}  {exc.hypothesis}")
            for subset in exc.alternatives or []:
                lines.append(f"        subset of {len(subset)}: {sorted(subset)[:2]}...")
    return "\n".join(lines)


def prepare_inputs(out: Path = BATCHES) -> list[str]:
    """Generate the batches if they are absent, then verify them either way.

    Verifying *after* generating rather than instead of it is the point: a run
    that regenerates unconditionally would silently repair a tampered batch and
    report clean numbers over rewritten bytes.
    """
    from .generator import main as generate
    from .generator import verify_manifest

    mpath = out / "MANIFEST.json"
    committed = mpath.read_text(encoding="utf-8") if mpath.exists() else None
    if not (out / "A" / "labels.json").exists():
        generate(["--out", str(out)])
        if committed is not None:
            # The generator rewrites the manifest from the bytes it just wrote,
            # so verifying against it would compare the batches with themselves
            # — an artifact carrying its own evidence, which is audit finding
            # `F1` in a third costume. The committed manifest is the independent
            # record, so it is put back before anything is checked.
            mpath.write_text(committed, encoding="utf-8")
    return verify_manifest(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench.run")
    ap.add_argument("--batch", default="all", choices=["A", "B", "all"])
    args = ap.parse_args(argv)

    problems = prepare_inputs()
    if problems:
        print("REFUSING to measure — batches do not match the committed manifest:")
        for line in problems:
            print(f"  {line}")
        return 2

    names = ["A", "B"] if args.batch == "all" else [args.batch]
    results = [close(name) for name in names]
    for result in results:
        print(render(result))
        print()

    print("the eight metrics: " + " · ".join(EIGHT_METRICS))
    failed = [r.batch for r in results if not r.ok]
    if failed:
        print(f"\nFAILED — batch(es) {failed} dropped a true pair or left an input undisposed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
