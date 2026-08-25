"""Behaviour is configuration, or invariant 7 is only true of field names.

`tiers.run` ran `for tier in (T0_EXACT, T1_TOLERANT)` — a literal tuple inside
the function. The engine took its side names, key names and signs from a profile
and its *behaviour* from a line of source nobody outside could see. A loop
needing a fourth way of matching needed an engine edit, which is the thing P15
exists to stop.

The refactor is asserted the only way a refactor can honestly be: the same close
produces the same `outcome_digest`, byte for byte, on both batches.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import replace
from pathlib import Path

import pytest
from bench.run import SETTLEMENT_3WAY, close

from recon.engine import strategies, tiers

#: Captured before the pipeline landed, from the literal-tuple implementation,
#: then re-captured when the `E04` plant changed the corpus. Re-pinning is only
#: honest because the refactor itself was proven digest-identical *first*, on the
#: corpus it was made against; a digest re-pinned to whatever the code now emits
#: asserts nothing.
BASELINE = {"A": "5d5a6958f5d17aeb5618ad87", "B": "51ae44dea18b4c6e5802cf64"}


@pytest.mark.parametrize("batch", ["A", "B"])
def test_the_pipeline_reproduces_the_hardcoded_sequence_exactly(batch):
    """The only honest assertion about a refactor: nothing moved."""
    assert close(batch).outcome_digest.startswith(BASELINE[batch])


def test_the_profile_decides_what_runs_and_removing_one_changes_the_answer():
    """The claim itself. If dropping a strategy from the profile changed
    nothing, the profile would not be deciding anything."""
    full = close("A", rules=[])
    assert full.matches

    no_tolerant = replace(SETTLEMENT_3WAY, strategies=("exact", "subset_sum"))
    reduced = tiers.run(
        [r for r in full.records.values() if r.side == "bank"],
        full.settlement_records,
        no_tolerant,
    )
    tiers_used = {m.tier.value for m in reduced.matches}

    assert "T1" not in tiers_used, "a strategy the profile did not declare still ran"
    assert len(reduced.matches) < len(full.matches), "removing a strategy changed nothing"


def test_order_is_the_profile_s_and_not_the_engine_s():
    """`exact` before `tolerant` is a decision, not a fact of nature. A group a
    stronger strategy claimed is not offered to a weaker one, so the order
    decides which tier a match is recorded at."""
    records = close("A", rules=[]).records
    anchors = [r for r in records.values() if r.side == "bank"]
    groups = [r for r in records.values() if r.side == "settlement"]

    forward = tiers.run(anchors, groups, SETTLEMENT_3WAY)
    swapped = tiers.run(
        anchors, groups, replace(SETTLEMENT_3WAY, strategies=("tolerant", "exact", "subset_sum"))
    )

    counts = lambda run: {t: sum(1 for m in run.matches if m.tier.value == t) for t in ("T0", "T1")}  # noqa: E731
    assert counts(forward) != counts(swapped), "order made no difference to the tier split"


def test_a_profile_naming_an_unknown_strategy_is_refused_before_anything_runs():
    """A configuration error, never an execution — the rule the parse verbs live
    under (ADR-001). Refused eagerly, so a typo in the fourth strategy fails at
    the top rather than three tiers in with half a ledger written."""
    with pytest.raises(strategies.StrategyError, match="unknown strategy"):
        strategies.resolve(("exact", "definitely_not_a_strategy"))


def test_a_profile_that_declares_nothing_is_refused():
    """An empty sequence would match nothing and report a clean 0% rather than
    an error, which is the shape of every silent failure in this codebase."""
    with pytest.raises(strategies.StrategyError, match="never match"):
        strategies.resolve(())


def test_a_strategy_cannot_see_a_group_another_already_claimed():
    """A group backs exactly one anchor. Re-offering a claimed group is how a
    match count starts exceeding the number of payouts."""
    source = inspect.getsource(tiers.run)
    assert "if ref not in claimed" in source or "not in claimed}" in source

    result = close("A", rules=[])
    claimed = [m.group_ref for m in result.matches]
    assert len(claimed) == len(set(claimed)), "a group backed two anchors"


def test_no_strategy_can_verify_or_post():
    """A strategy proposes; the checker checks. One that could do both would be
    marking its own homework, which is the failure this project has now found in
    five other costumes."""
    tree = ast.parse(Path(strategies.__file__).read_text())
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for forbidden in ("verify", "entries_for", "post_and_assert"):
        assert forbidden not in called, f"a strategy calls {forbidden}"


def test_every_registered_strategy_is_reachable_from_a_profile():
    """A registry entry no profile can name is a capability that exists only in
    a test — the shape four action kinds shipped in."""
    declared = set(SETTLEMENT_3WAY.strategies)
    known = set(strategies.STRATEGIES) | strategies.POOL_STRATEGIES

    assert declared <= known
    assert known - declared == set(), (
        f"{sorted(known - declared)} is registered and no shipped profile uses it; "
        "either declare it or delete it"
    )


def _offer(anchor, groups, allowed=None):
    from decimal import Decimal

    from recon.engine.strategies import Offer

    return Offer(
        anchor=anchor,
        available=groups,
        allowed=allowed,
        profile=SETTLEMENT_3WAY,
        residual=lambda a, g: sum((r.amount for r in g), Decimal("0.00")) - a.amount,
    )


def test_no_strategy_proposes_a_group_blocking_ruled_out():
    """Asserted directly, because the batches cannot assert it.

    Blocking bites hard here — 74.5% reduction, every matched anchor on a strict
    subset — and yet deleting the filter changed no answer, because widening the
    candidate set never produced a second viable group on this data. A control
    that only bites on inputs we happen not to have is a control nobody has
    tested, so this constructs the input.
    """
    result = close("A", rules=[])
    grouped: dict[str, list] = {}
    for record in result.settlement_records:
        if record.group_ref:
            grouped.setdefault(record.group_ref, []).append(record)
    anchor = next(r for r in result.records.values() if r.side == "bank" and r.source_row_id)

    wide = _offer(anchor, grouped, allowed=None)
    narrow = _offer(anchor, grouped, allowed=set())

    for name, strategy in strategies.STRATEGIES.items():
        assert strategy(narrow) is None, f"{name} proposed a group blocking excluded"
        proposed = strategy(wide)
        if proposed is not None:
            assert proposed.group_ref in grouped, name


def test_the_driver_owns_the_tolerance_budget_not_the_strategy():
    """`_exact` used to re-check the residual the driver already checks. Both
    were right and one was redundant, which is the shape of a copy that rots.

    So the tier contract is asserted where it now lives: a `T0` proposal whose
    residual is not zero must not become a match."""
    source = inspect.getsource(tiers.run)
    assert "if residual != ZERO:" in source, "the driver stopped enforcing T0's contract"

    result = close("A", rules=[])
    for match in result.matches:
        if match.tier.value == "T0":
            assert match.proof.residual == 0, match.match_id
