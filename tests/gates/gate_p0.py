"""Gate P0 — synthetic generator + ground truth.

Gate: generator emits batch A and B with complete labels; adversarial cases
present; a second person can regenerate identical batches from a seed.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest
from bench.adversarial.cases import CASES
from bench.generator import BATCHES, build, check_batch, emit

pytestmark = pytest.mark.gate


def _digests(root: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.iterdir())
        if p.is_file()
    }


@pytest.mark.parametrize("name,seed,start", BATCHES, ids=[b[0] for b in BATCHES])
def test_seed_reproduces_batch_byte_for_byte(tmp_path, name, seed, start):
    """The gate's core claim: a seed is enough to regenerate the batch exactly."""
    first = emit(build(name, seed, start), tmp_path / "first")
    second = emit(build(name, seed, start), tmp_path / "second")
    assert set(first) == set(second)
    assert _digests(tmp_path / "first") == _digests(tmp_path / "second")


def test_different_seeds_produce_different_batches(tmp_path):
    """Guards against a generator that ignores its seed and looks reproducible."""
    a = emit(build("A", BATCHES[0][1], BATCHES[0][2]), tmp_path / "a")
    b = emit(build("B", BATCHES[1][1], BATCHES[1][2]), tmp_path / "b")
    assert _digests(tmp_path / "a") != _digests(tmp_path / "b")
    assert a.keys() == b.keys()


@pytest.mark.parametrize("name,seed,start", BATCHES, ids=[b[0] for b in BATCHES])
def test_unreconciled_totals_cross_check(name, seed, start):
    """Recomputed from the structures, never from the planted list."""
    totals = check_batch(build(name, seed, start))
    assert totals["bank_leg"] > 0, "a batch with no bank-leg defect tests nothing"
    assert totals["orders_leg"] > 0


@pytest.mark.parametrize("name,seed,start", BATCHES, ids=[b[0] for b in BATCHES])
def test_labels_are_complete(tmp_path, name, seed, start):
    batch = build(name, seed, start)
    labels = json.loads(emit(batch, tmp_path / name)["labels"].read_text())

    assert labels["counts"]["payouts"] == len(batch.payouts)
    assert labels["counts"]["orders"] == len(batch.orders)
    assert labels["counts"]["bank_lines"] == len(batch.bank)

    # Every payout and every order is present in the ground truth, not a sample.
    assert set(labels["payout_membership"]) == {p.payout_id for p in batch.payouts}
    assert set(labels["order_to_payment"]) == {o.order_id for o in batch.orders}

    # Every settlement row belongs to exactly one payout.
    seen: set[str] = set()
    for entry in labels["payout_membership"].values():
        rows = entry["charges"] + entry["refunds"] + entry["fees"]
        assert not (seen & set(rows)), "a row is claimed by two payouts"
        seen.update(rows)

    codes = {e["code"] for e in labels["expected_exceptions"]}
    assert {"E01", "E02", "E06", "E07", "E08", "E09"} <= codes


@pytest.mark.parametrize("name,seed,start", BATCHES, ids=[b[0] for b in BATCHES])
def test_ambiguous_case_declares_competing_subsets(name, seed, start):
    """E09's label must be 'ambiguous', not a preferred answer — a grader has to
    be able to confirm the ambiguity rather than trust the generator."""
    batch = build(name, seed, start)
    e09 = [e for e in batch.planted if e.code == "E09"]
    assert e09, "no ambiguity planted"
    for exc in e09:
        subsets = exc.ambiguous_subsets
        assert subsets and len(subsets) >= 2
        assert len(set(map(tuple, subsets))) == len(subsets), "subsets must be distinct"
        flat = [r for s in subsets for r in s]
        assert len(flat) == len(set(flat)), "subsets must be disjoint"


def test_adversarial_cases_present_and_specified():
    assert len(CASES) >= 10
    assert len({c.id for c in CASES}) == len(CASES)
    for case in CASES:
        assert case.situation and case.trap and case.correct_behaviour and case.expect
        assert case.trap != case.correct_behaviour


def test_adversarial_set_is_independent_of_the_engine():
    """CLAUDE.md rule 1: the adversarial set is authored independently. If it can
    import engine code it will drift toward what the engine already does."""
    src = Path("bench/adversarial/cases.py").read_text()
    imported = {
        node.module.split(".")[0]
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "recon" not in imported, f"adversarial set imports engine code: {sorted(imported)}"
