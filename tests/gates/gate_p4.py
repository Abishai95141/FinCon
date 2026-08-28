"""Gate P4 — blocking + measured recall.

Gate: blocking recall is measured against batch A's labels and printed on the
scorecard.

Two hazards this gate exists to close. First, blocking must not change any P3
number — a blocker that quietly improves the match rate has changed the answer,
not the search. Second, splitting losses into `dropped` and `unreachable` must
not become a way to launder blocking failures: a pair whose group IS declared
and which blocking fails to propose has to be counted as dropped, and that is
asserted directly rather than assumed.
"""

from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

import pytest
from bench.arms import deterministic
from bench.metrics import truth_groups
from bench.run import BATCHES, SETTLEMENT_3WAY, SETTLEMENT_POLICY, load_sides

from recon.engine.blocking import (
    BlockingPolicy,
    CandidateSet,
    build,
    recall,
    summarise_groups,
)
from recon.engine.tiers import run as run_tiers

pytestmark = pytest.mark.gate


@pytest.fixture(scope="module", autouse=True)
def _batches_exist():
    if not (BATCHES / "A" / "labels.json").exists():
        pytest.skip("run `make gen` first — P4 reads the P0 batches")


@pytest.fixture(scope="module")
def sides():
    return {b: load_sides(b) for b in ("A", "B")}


def _parts(sides, batch):
    bank, settlement, provenance = sides[batch].in_scope()
    anchors = [rec for _, rec in bank]
    groups = [rec for _, rec in settlement]
    declared = {rec.group_ref for rec in groups if rec.group_ref}
    return bank, settlement, provenance, anchors, groups, declared


#: The settlement loop's own blocking policy, read from the loop rather than
#: retyped. `BlockingPolicy` no longer defaults to `"gateway"` — that key sat in
#: the kernel as the value every other loop silently inherited, which is why the
#: TDS loop blocked nothing. Naming it again here would just move the copy.
SETTLEMENT_BLOCKING = BlockingPolicy(
    counterparty_key=SETTLEMENT_3WAY.counterparty_key,
    date_window_days=SETTLEMENT_3WAY.tolerance.date_window_days or 3,
)


def _measure(sides, batch, policy: BlockingPolicy | None = None):
    bank, _s, _p, anchors, groups, declared = _parts(sides, batch)
    labels = BATCHES / batch / "labels.json"
    candidates = build(anchors, groups, policy or SETTLEMENT_BLOCKING)
    return candidates, recall(
        candidates,
        truth_groups(labels),
        {ext: rec.record_id for ext, rec in bank},
        declared_groups=declared,
    )


# --------------------------------------------------------------------------
# the gate proper
# --------------------------------------------------------------------------


@pytest.mark.parametrize("batch", ["A", "B"])
def test_blocking_keeps_every_reachable_true_pair(sides, batch):
    _candidates, report = _measure(sides, batch)
    assert report.reachable == 21
    assert report.dropped == [], f"blocking dropped a true pair: {report.dropped}"
    assert report.recall == 1.0


@pytest.mark.parametrize("batch", ["A", "B"])
def test_unreachable_pairs_are_counted_and_named(sides, batch):
    """The E09 payout's rows carry no group_ref, so no (anchor, group) pair was
    ever presented to the blocker. Counting it as a blocking drop would blame
    the wrong layer — but it must still be visible, not omitted."""
    _candidates, report = _measure(sides, batch)
    labels = json.loads((BATCHES / batch / "labels.json").read_text())
    assert {payout for _, payout in report.unreachable} == set(labels["ungrouped_payouts"])
    assert report.true_pairs == report.reachable + len(report.unreachable) == 22
    assert "not reachable at all" in report.render()


def test_unreachable_cannot_absorb_a_real_blocking_failure(sides):
    """The load-bearing test. If a pair whose group IS declared goes missing
    from the candidate set, it must land in `dropped` — otherwise the
    reachable/unreachable split is an escape hatch rather than an attribution.
    """
    bank, _s, _p, anchors, groups, declared = _parts(sides, "A")
    labels = BATCHES / "A" / "labels.json"
    truth = truth_groups(labels)
    anchor_ids = {ext: rec.record_id for ext, rec in bank}

    full = build(anchors, groups, SETTLEMENT_BLOCKING)
    victim_ext = next(ext for ext, payout in sorted(truth.items()) if payout in declared)
    victim = (anchor_ids[victim_ext], truth[victim_ext])
    assert victim in full.pairs

    sabotaged = CandidateSet(
        pairs=frozenset(full.pairs - {victim}),
        anchors=full.anchors,
        groups=full.groups,
        by_block=full.by_block,
    )
    report = recall(sabotaged, truth, anchor_ids, declared_groups=declared)

    assert victim_ext in [ext for ext, _ in report.dropped]
    assert victim_ext not in [ext for ext, _ in report.unreachable]
    assert report.recall < 1.0
    assert "DROPPED" in report.render()


@pytest.mark.parametrize("batch", ["A", "B"])
def test_blocking_does_not_change_any_p3_number(sides, batch):
    """A blocker narrows the search. If it changes the answer it is not a
    blocker — it is a matching rule wearing one's clothes."""
    _bank, _settlement, provenance, anchors, groups, _declared = _parts(sides, batch)

    # Asserted against `engine.tiers.run`, which is the seam that actually honours
    # a candidate set. This test used to call `deterministic.run` twice, passing
    # `None` and then a set — and that arm ignored the argument, so both calls
    # were the same call and the assertion could not fail. A gate over an effect
    # that never happens; found 2026-08-28 while tracing why the scorecard
    # printed two different blocking figures.
    without = run_tiers(anchors, groups, SETTLEMENT_3WAY, provenance, None, SETTLEMENT_POLICY)
    with_blocking = run_tiers(
        anchors,
        groups,
        SETTLEMENT_3WAY,
        provenance,
        build(anchors, groups, SETTLEMENT_BLOCKING),
        SETTLEMENT_POLICY,
    )

    def pairing(outcome):
        return {m.anchor_id: frozenset(m.group_ids) for m in outcome.matches}

    assert pairing(with_blocking) == pairing(without), (
        "blocking changed the answer, which makes it a matching rule rather than "
        "a narrowing of the search"
    )
    assert {e.code for e in with_blocking.exceptions} == {e.code for e in without.exceptions}


@pytest.mark.parametrize("batch", ["A", "B"])
def test_the_reported_blocking_is_the_blocking_that_happened(sides, batch):
    """Invariant 6 must be measured on the set the matcher actually used.

    `bench/run.py` built its own candidate set with a bare `BlockingPolicy()`,
    printed *that* on the scorecard, and measured recall against it — while the
    close narrowed with the loop's own policy. Two numbers for one fact: 271
    pairs reported, 150 considered, and 121 the recall counted reachable that no
    close ever looked at. Recall read 100% on a superset of the real one, which
    can only ever overstate.

    So: the arm reports the set it matched over, and this asserts it is the
    loop's, not the kernel default. The second assertion is the one that matters
    — without it the first passes on any two sets that happen to agree.
    """
    anchors = [rec for _, rec in sides[batch].bank]
    groups = [rec for _, rec in sides[batch].settlement]

    result = deterministic.run(
        sides[batch].bank,
        sides[batch].settlement,
        SETTLEMENT_3WAY,
        SETTLEMENT_POLICY,
        sides[batch].provenance,
        sides[batch].scope,
    )

    assert result.candidates is not None, "an arm that blocks must report what it blocked with"
    assert result.candidates.pairs == build(anchors, groups, SETTLEMENT_BLOCKING).pairs, (
        "the arm matched over a different candidate set than the loop's policy builds"
    )
    kernel_default = build(anchors, groups, BlockingPolicy())
    assert result.candidates.pairs != kernel_default.pairs, (
        "the loop's blocking is indistinguishable from the kernel default here, so "
        "this test cannot tell the two apart and the regression it guards would pass"
    )


@pytest.mark.parametrize("batch", ["A", "B"])
def test_blocking_actually_reduces_the_search(sides, batch):
    candidates, _ = _measure(sides, batch)
    assert candidates.considered < candidates.exhaustive
    assert candidates.reduction > 0.5
    assert candidates.exhaustive == candidates.anchors * candidates.groups


def test_blocks_are_unioned_not_intersected(sides):
    """Intersecting would mean every block must agree, so one imperfect block
    would silently cap the system. A pair proposed by only the reference block
    must survive even when the others would reject it."""
    _bank, _s, _p, anchors, groups, _declared = _parts(sides, "A")

    # A policy where amount and date can propose nothing: no counterparty will
    # ever agree, so only the reference block can contribute.
    blind = BlockingPolicy(
        amount_bucket=D("0.01"), date_window_days=0, counterparty_key="no_such_key"
    )
    candidates = build(anchors, groups, blind)
    assert candidates.by_block["reference"] > 0
    assert candidates.considered >= candidates.by_block["reference"]
    assert candidates.pairs, "an intersection would have emptied this"


def test_every_block_contributes_something(sides):
    """A block that never fires is dead weight that still costs a scan. If one
    drops to zero, either the data changed or the block is misconfigured."""
    candidates, _ = _measure(sides, "A")
    assert set(candidates.by_block) == {"reference", "amount", "date"}
    for name, count in candidates.by_block.items():
        assert count > 0, f"block {name!r} proposed nothing"


def test_groups_for_matches_the_pair_set(sides):
    candidates, _ = _measure(sides, "A")
    by_anchor: dict[str, set[str]] = {}
    for anchor, group in candidates.pairs:
        by_anchor.setdefault(anchor, set()).add(group)
    for anchor, expected in by_anchor.items():
        assert candidates.groups_for(anchor) == expected


def test_group_summaries_span_their_rows(sides):
    _bank, _s, _p, _anchors, groups, _declared = _parts(sides, "A")
    summaries = summarise_groups(groups, BlockingPolicy())
    assert summaries
    for summary in summaries.values():
        rows = [r for r in groups if r.group_ref == summary.group_ref]
        assert summary.total == sum(r.amount for r in rows)
        assert summary.earliest == min(r.posted_on for r in rows)
        assert summary.latest == max(r.posted_on for r in rows)
        assert summary.earliest <= summary.latest


def test_runner_prints_recall_and_fails_on_a_dropped_pair():
    """Invariant 6: the number is on the page every run. And a dropped true
    pair is a failed run, not a footnote — the runner's exit code says so."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "bench.run", "--batch", "A"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )
    assert proc.returncode == 0, proc.stdout
    assert "blocking recall" in proc.stdout
    assert "reduction" in proc.stdout
    # Recall is printed above the match rates, so it cannot be skimmed past.
    assert proc.stdout.index("blocking recall") < proc.stdout.index("auto-match")
