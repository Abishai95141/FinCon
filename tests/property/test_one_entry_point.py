"""There is an application, and the benchmark is a caller rather than the thing.

Before A1, `bench/run.py:close()` was the only code that assembled intake ->
tiers -> ledger -> journal -> worklist, and `src/recon/api/` and
`src/recon/mcp/` were empty files. `src/recon` was a library with no
application. A runtime trace of one close executed 135 of 254 functions in
`src/recon`; `engine/promotion.py` was 20/20 never run and the whole of
`triage/` 31/31, because the only thing that ever called them was a test.

That is what made "a control over an effect that never happens" possible: a
control only a test drives can be checked on its inputs, and outside a test it
has no outputs to check.
"""

from __future__ import annotations

import ast
import inspect
from datetime import date
from pathlib import Path

from bench.run import (
    CHART,
    RUNS,
    SETTLEMENT_3WAY,
    SETTLEMENT_POLICY,
    TAXONOMY,
    WINDOW,
    close,
    load_sides,
)

from recon.close import CloseRequest, match_and_verify, run_close
from tests.conftest import promoted


def _request(batch: str, tmp: Path, **over) -> CloseRequest:
    sides = load_sides(batch)
    base = dict(
        run_id=batch,
        anchors=sides.bank,
        groups=sides.settlement,
        profile=SETTLEMENT_3WAY,
        policy=SETTLEMENT_POLICY,
        taxonomy=TAXONOMY,
        chart=CHART,
        period=WINDOW,
        opened_on=date(2026, 7, 1),
        journal_path=tmp / "decisions.jsonl",
        source_proofs=sides.proofs,
        provenance=sides.provenance,
        out_of_scope=sides.scope,
    )
    base.update(over)
    return CloseRequest(**base)


def test_the_product_configures_and_closes_with_no_benchmark_import(tmp_path):
    """The strongest form of A1's claim, and the one the other tests in this
    file do not make: they import `SETTLEMENT_3WAY`, `CHART` and `WINDOW` from
    `bench.run`, which for months was where the product's own configuration
    lived. This touches nothing under `bench/`.
    """
    import sys

    from recon.close import CloseRequest, run_close
    from recon.intake import ingest, load_spec
    from recon.profiles import settlement

    root = Path("data/batches/A")
    pol = settlement.policy()
    bank = ingest(load_spec("icici-camt"), root / "bank_icici_camt053.xml", settlement.WINDOW, pol)
    gate = ingest(load_spec("gateway-settlement"), root / "settlement.csv", settlement.WINDOW, pol)

    outcome = run_close(
        CloseRequest(
            run_id="no-bench",
            anchors=[(r.keys["entry_ref"], r) for r in bank.records],
            groups=[(r.source_row_id, r) for r in gate.records if r.source_row_id],
            profile=settlement.PROFILE,
            policy=pol,
            taxonomy=settlement.taxonomy(),
            chart=settlement.chart(),
            period=settlement.WINDOW,
            opened_on=settlement.OPENED_ON,
            journal_path=tmp_path / "decisions.jsonl",
            source_proofs=[bank.proof, gate.proof],
            out_of_scope={
                r.record_id: "debit — this loop reconciles receipts"
                for r in bank.records
                if r.amount <= 0
            },
        )
    )
    assert outcome.matches and outcome.entries and outcome.journal_path.exists()
    assert outcome.outcome_digest

    # And the product half never reaches for the harness, however it was called.
    assert not [m for m in sys.modules if m.startswith("recon.") and "bench" in m]
    for module in (
        m for m in sys.modules.values() if getattr(m, "__name__", "").startswith("recon.")
    ):
        src = getattr(module, "__file__", "") or ""
        assert "/bench/" not in src, module.__name__


def test_a_close_runs_without_the_benchmark(tmp_path):
    """The claim A1 exists to make true. No labels, no arms, no scorecard — the
    product's own path, reaching the books and writing its own record."""
    outcome = run_close(_request("A", tmp_path))

    assert outcome.matches, "no match"
    assert outcome.entries, "nothing reached the books"
    assert outcome.journal_path.exists(), "no decision log"
    assert outcome.worklist, "no queue for a human"
    assert outcome.completeness.complete, "invariant 8"
    assert outcome.ok


def test_the_terminal_event_can_be_written_without_truth_labels():
    """The entanglement A1 surfaced. The terminator committed to a digest of the
    *benchmark scorecard*, which is computed against labels — so a close run
    anywhere but the benchmark could not write its own terminal event, and
    "replay a close from its log" quietly meant "replay a close that has
    labels"."""
    import tempfile

    from recon.contracts import EventKind
    from recon.journal import read

    with tempfile.TemporaryDirectory() as tmp:
        outcome = run_close(_request("A", Path(tmp)))
        events = list(read(outcome.journal_path))

    terminator = next(e for e in reversed(events) if e.kind is EventKind.CLOSE_COMPLETED)
    assert terminator.payload.outcome_digest == outcome.outcome_digest
    assert len(terminator.payload.outcome_digest) == 64
    assert terminator.payload.scorecard_digest == "", (
        "a close with no way to score must not claim a scorecard digest"
    )


def test_the_outcome_digest_moves_when_a_decision_moves(tmp_path):
    """A digest that never moves commits to nothing. It must also *not* move on
    a re-run, or replay could never agree with the run."""
    from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction

    plain = run_close(_request("A", tmp_path / "a"))
    again = run_close(_request("A", tmp_path / "b"))
    assert plain.outcome_digest == again.outcome_digest, "not reproducible"

    rule = promoted(
        Rule(
            rule_id="R-DIG",
            profile="settlement_3way",
            when=[Predicate(field="key_occurrence", op=Operator.GT, value="0")],
            then=[RuleAction(kind=ActionKind.SUPPRESS, reason="a repeat")],
        )
    )
    ruled = run_close(_request("A", tmp_path / "c", rules=[rule]))
    assert ruled.outcome_digest != plain.outcome_digest


def test_the_benchmark_and_a_close_agree_because_they_are_the_same_code(tmp_path):
    """Two paths that agree by inspection eventually stop agreeing. These agree
    because there is one of them."""
    # Same inputs on both sides, promoted store included — the benchmark loads
    # it by default, so a helper that passed no rules would be comparing two
    # different closes and calling the difference agreement.
    from recon.engine import rulestore

    rules = rulestore.load(SETTLEMENT_3WAY.name)
    direct = run_close(_request("A", tmp_path, rules=rules))
    viaBench = close("A", journal_dir=tmp_path / "bench")

    assert len(direct.matches) == len(viaBench.matches)
    assert direct.outcome_digest == viaBench.outcome_digest
    assert sorted(e.code for e in direct.exceptions) == sorted(e.code for e in viaBench.exceptions)


def test_the_deterministic_arm_is_an_adapter_not_a_second_implementation():
    """It called `run_tiers` and then verified every match itself — a second
    implementation of matching-and-verification beside the one a close used."""
    from bench.arms import deterministic

    source = inspect.getsource(deterministic)
    tree = ast.parse(source)
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "match_and_verify" in called
    assert "run_tiers" not in called, "the arm matches on its own again"
    assert "verify" not in called, "the arm verifies on its own again"


def test_the_pipeline_does_not_live_in_the_benchmark():
    """The structural claim, asserted so it cannot quietly revert: posting,
    journalling and the worklist are the product's, and `bench/run.py` may call
    them but must not be where they happen."""
    tree = ast.parse(Path("bench/run.py").read_text())
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "run_close" in called
    for owned_by_the_product in ("entries_for", "post_and_assert", "derive", "build_worklist"):
        assert owned_by_the_product not in called, (
            f"{owned_by_the_product} is being called from the benchmark again; "
            "the harness is a driving adapter, not the pipeline"
        )


def test_matching_and_verification_are_one_stage(tmp_path):
    """An unverified match is not a match (invariant 2), and that has to be true
    of every caller of the stage rather than of every caller who remembers."""
    staged = match_and_verify(_request("A", tmp_path))
    assert staged.matches
    assert all(m.proof.provenance is not None for m in staged.matches)
    assert len(staged.matches) + len(staged.rejected) == len(staged.run.matches)


def test_a_close_writes_its_journal_where_it_was_told(tmp_path):
    """`RUNS` is a benchmark default. The product takes a path."""
    outcome = run_close(_request("A", tmp_path / "nested" / "deeper"))
    assert outcome.journal_path == tmp_path / "nested" / "deeper" / "decisions.jsonl"
    assert RUNS not in outcome.journal_path.parents
