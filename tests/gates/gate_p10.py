"""Gate P10 — measurement. ◆ SHIP LINE.

Gate: `make eval` produces the full comparison on A and B from a clean
checkout, one command.

Written before the implementation. Four things this gate exists to stop, each
of which the build has already done once in some other costume:

* **A zero standing in for an absence.** The LLM arm has not been built. A row
  of `0.0%` reads as "it tried and failed" — a claim we have not earned. An arm
  that did not run must refuse to produce a number at all.
* **A headline without its decomposition.** `90.9%` is gameable; `90.9%
  (20/22)` beside a false-match rate and a tier split is not. CLAUDE.md rule 1
  names this one directly.
* **A denominator we get to choose.** Exception coverage measured against the
  exceptions we happened to surface is a tautology. The denominator comes from
  the P0 labels, and what is in scope comes from the label's own `leg`.
* **Measuring inputs nobody checked.** "From a clean checkout" is only true if
  the batches on disk are the ones the committed manifest describes.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

pytestmark = pytest.mark.gate

BATCHES = Path("data/batches")


@pytest.fixture(scope="module", autouse=True)
def _batches_exist():
    if not (BATCHES / "A" / "labels.json").exists():
        pytest.skip("run `make gen` first — P10 measures the P0 batches")


@pytest.fixture(scope="module")
def closes():
    from bench.run import close

    return {name: close(name) for name in ("A", "B")}


@pytest.fixture(scope="module")
def card_index(closes):
    return {b: {c.arm: c for c in r.cards} for b, r in closes.items()}


# --------------------------------------------------------------------------
# the gate proper — one command, both batches, four arms, eight metrics
# --------------------------------------------------------------------------


def test_one_command_produces_the_full_comparison_on_both_batches(capsys):
    """The gate sentence, executed. `main()` with no arguments must measure A
    *and* B — a runner defaulting to one batch lets the held-out set rot."""
    from bench.run import main

    assert main([]) == 0
    out = capsys.readouterr().out
    for batch in ("A", "B"):
        assert f"batch {batch}" in out, f"batch {batch} missing from the one-command output"
    for arm in ("securo_raw", "securo_grouped", "deterministic", "llm_only"):
        assert arm in out, f"arm {arm} missing"


def test_every_metric_is_named_in_the_output(capsys):
    """A reader must be able to tick them off against the page rather than take
    our word for the count."""
    from bench.metrics import METRICS
    from bench.run import main

    # Nine, not the plan's eight. The LLM-only arm exposed a gap: `auto-match`
    # scores linkage against labels that, for the planted `E06`, do not balance
    # — so an arm naming an unprovable pairing scores *correct* and the engine
    # scores a *miss* for refusing it. `unprovable matches` tells them apart.
    assert len(METRICS) == 9
    main([])
    out = capsys.readouterr().out
    missing = [m for m in METRICS if m not in out]
    assert not missing, f"metrics claimed but not rendered: {missing}"


def test_every_arm_is_scored_on_both_batches(card_index):
    for batch, cards in card_index.items():
        assert set(cards) == {"securo_raw", "securo_grouped", "deterministic", "llm_only"}, batch


# --------------------------------------------------------------------------
# absent is not zero
# --------------------------------------------------------------------------


def test_the_llm_arm_reports_absent_not_zero(card_index):
    """An arm that has not been built is *absent*. A zero says we ran it and it
    scored nothing, which would be a claim about a model we never called."""
    card = card_index["A"]["llm_only"]
    assert card.absent, "the LLM arm must declare itself absent"
    rendered = card.render()
    assert "absent" in rendered
    assert "0.0%" not in rendered and "0.00%" not in rendered, (
        f"an absent arm rendered a zero: {rendered!r}"
    )


def test_an_absent_arm_refuses_to_produce_a_number(card_index):
    """Not merely 'renders differently' — the number must be unavailable. A
    property returning 0.0 would be read by the next caller as a measurement."""
    from bench.metrics import ArmAbsent

    card = card_index["A"]["llm_only"]
    for name in ("auto_match_rate", "false_match_rate", "precision", "recall"):
        with pytest.raises(ArmAbsent):
            getattr(card, name)


def test_an_absent_arm_cannot_carry_results(card_index):
    """The trap: declare an arm absent, then quietly hand it pairs so a later
    aggregate picks them up. Absence must be exclusive."""
    from bench.metrics import Scorecard

    with pytest.raises(ValueError):
        Scorecard(arm="llm_only", absent="no model", produced=7, true_pairs=22)


# --------------------------------------------------------------------------
# every rate ships with its decomposition
# --------------------------------------------------------------------------


def test_every_rate_carries_its_decomposition(card_index):
    """CLAUDE.md rule 1: a headline rate alone is gameable. The rate object
    renders its own numerator and denominator, so printing it bare still shows
    what it is made of."""
    card = card_index["A"]["deterministic"]
    rendered = str(card.auto_match_rate)
    assert "%" in rendered and "/" in rendered, rendered
    assert f"{card.correct}" in rendered or f"{card.produced}" in rendered


def test_a_tier_split_that_does_not_account_for_every_match_is_refused():
    """A match the arm counts but no tier produced is a match with no provenance.
    Invariant 2 in scorecard form."""
    from bench.metrics import Scorecard

    with pytest.raises(ValueError):
        Scorecard(
            arm="x", true_pairs=22, produced=20, correct=20, tiers={"T0": 18}, records_scored=1
        )


def test_an_arm_that_produced_matches_must_say_how(card_index):
    from bench.metrics import Scorecard

    with pytest.raises(ValueError):
        Scorecard(arm="x", true_pairs=22, produced=20, correct=20, tiers=None, records_scored=1)

    for arm in ("securo_raw", "securo_grouped", "deterministic"):
        card = card_index["A"][arm]
        assert card.tiers is not None
        assert sum(card.tiers.values()) == card.produced, arm


def test_the_headline_cannot_be_rendered_without_the_false_match_rate(card_index):
    card = card_index["A"]["deterministic"]
    line = card.headline()
    assert "auto-match" in line and "false-match" in line and "tiers" in line


# --------------------------------------------------------------------------
# exception honesty — measured against P0's labels, not against ourselves
# --------------------------------------------------------------------------


def test_exception_coverage_is_measured_against_the_planted_labels(card_index):
    """Metric 5. The denominator is what P0 planted, so surfacing nothing
    scores zero rather than being undefined."""
    card = card_index["A"]["deterministic"]
    planted = json.loads((BATCHES / "A" / "labels.json").read_text())["expected_exceptions"]
    score = card.exceptions
    assert score is not None
    assert score.planted_in_scope + len(score.out_of_scope) == len(planted)
    assert score.planted_in_scope > 0
    assert score.coverage.denominator == score.planted_in_scope


def test_the_baseline_ties_on_match_rate_and_surfaces_nothing(card_index):
    """The finding P3 could not show and this phase exists to make visible.

    `securo_grouped` matches exactly what we match — P3 asserted the pairs are
    identical. If the match rate were the whole story we would have built
    nothing. The difference is the tail, and until this phase nothing measured
    it."""
    cards = card_index["A"]
    ours, theirs = cards["deterministic"], cards["securo_grouped"]
    assert ours.auto_match_rate.value == theirs.auto_match_rate.value
    assert theirs.exceptions.surfaced == 0
    assert theirs.exceptions.coverage.value == 0.0
    assert ours.exceptions.surfaced > theirs.exceptions.surfaced, (
        "if we do not surface more than the baseline, this project has no thesis"
    )


def test_classification_accuracy_counts_only_the_right_code(card_index):
    """Metric 6. Noticing and naming are different capabilities and are scored
    separately — the deterministic engine can do the first and mostly cannot do
    the second, which is precisely the gap P12 has to close."""
    card = card_index["A"]["deterministic"]
    score = card.exceptions
    assert score.classified <= score.surfaced
    assert score.classification.denominator == score.planted_in_scope
    # E09 is the one the engine can name from arithmetic alone.
    assert score.classified >= 1


def test_a_surfaced_exception_with_the_wrong_code_is_not_classified():
    """The metric's teeth. E14 means 'I noticed and cannot say why' — counting
    it as a correct classification would make the honesty code score like an
    answer."""
    from bench.planted import PlantedException, score_planted

    from recon.contracts import ExceptionCode, ReconException

    planted = [PlantedException(code="E01", leg="bank", subject="p1", record_ids={"r1"})]
    raised = [
        ReconException(
            exception_id="EXC-1",
            code=ExceptionCode.E14_UNEXPLAINED,
            as_of=__import__("datetime").date(2026, 8, 1),
            amount=D("10.00"),
            record_ids=["r1"],
        )
    ]
    score = score_planted(planted, raised, in_scope_legs={"bank"})
    assert score.surfaced == 1
    assert score.classified == 0


def test_the_out_of_scope_split_cannot_absorb_a_missed_in_scope_exception():
    """The P4 precedent, applied here. `dropped` vs `unreachable` was an
    attribution, not an escape hatch, and the gate proved it. Same rule: a
    planted exception on a leg we run and did not surface lands in `missed`,
    never in `out_of_scope`."""
    from bench.planted import PlantedException, score_planted

    planted = [
        PlantedException(code="E02", leg="bank", subject="p1", record_ids={"r1"}),
        PlantedException(code="E07", leg="orders", subject="p2", record_ids={"r2"}),
    ]
    score = score_planted(planted, [], in_scope_legs={"bank"})
    assert score.planted_in_scope == 1
    assert [p.code for p in score.out_of_scope] == ["E07"]
    assert score.missed == ["E02"], score.missed
    assert score.coverage.value == 0.0


def test_scope_comes_from_the_labels_not_from_the_run(closes):
    """The denominator must not shrink when the run narrows its own scope.

    Declaring a hard anchor out of scope is the obvious way to make a coverage
    number look good, so scope for *measurement* is read from the label's `leg`,
    authored at P0, and never from what the run chose to look at."""
    from bench.planted import load_planted
    from bench.run import IN_SCOPE_LEGS

    result = closes["A"]
    planted = load_planted(BATCHES / "A" / "labels.json", result.external_of)
    in_scope = [p for p in planted if p.leg in IN_SCOPE_LEGS]
    card = {c.arm: c for c in result.cards}["deterministic"]
    assert card.exceptions.planted_in_scope == len(in_scope)
    # The E08 line is a bank credit the run could legitimately have declared
    # uninteresting. It stays in the denominator either way.
    assert any(p.code == "E08" for p in in_scope)


# --------------------------------------------------------------------------
# ambiguity detection — metric 7
# --------------------------------------------------------------------------


def test_ambiguity_detection_compares_against_the_planted_subsets(card_index):
    """Not 'did an E09 appear' — an E09 with the wrong subsets is a wrong
    answer wearing the right code."""
    card = card_index["A"]["deterministic"]
    score = card.exceptions
    assert score.ambiguity.denominator == 1
    assert score.ambiguity_detected == 1


def test_the_scorer_actually_compares_the_subsets_it_was_given():
    """Found by mutation. `subsets_agree` was tested on its own and the scoring
    path was tested only on a batch where the subsets happen to agree — so
    dropping the comparison from `score_planted` and accepting any `E09` on the
    right rows survived the whole gate. A helper nothing is forced to call is
    not a control. Same shape as the weak test P8 found in itself."""
    from bench.planted import PlantedException, score_planted

    from recon.contracts import ExceptionCode, ReconException

    planted = [
        PlantedException(
            code="E09",
            leg="bank",
            subject="p1",
            record_ids=frozenset({"a", "b", "c", "d"}),
            alternatives=(frozenset({"a", "b"}), frozenset({"c", "d"})),
        )
    ]

    def e09(alternatives):
        return ReconException(
            exception_id="EXC-1",
            code=ExceptionCode.E09_NETTING_AMBIGUITY,
            as_of=date(2026, 8, 1),
            amount=D("10.00"),
            record_ids=["a"],
            alternatives=alternatives,
            hypothesis="two subsets",
        )

    right = score_planted(planted, [e09([["a", "b"], ["c", "d"]])], in_scope_legs={"bank"})
    assert right.ambiguity_detected == 1

    wrong = score_planted(planted, [e09([["a", "c"], ["b", "d"]])], in_scope_legs={"bank"})
    assert wrong.surfaced == 1, "the defect was still noticed"
    assert wrong.ambiguity_detected == 0, (
        "an E09 naming the wrong subsets is a wrong answer wearing the right code"
    )
    assert "SUBSETS DISAGREE" in "\n".join(wrong.detail)


def test_over_reporting_ambiguity_is_not_a_detection():
    """P5 found the solver reporting four subsets where two exist. Four is a
    wrong answer about the data, and a detection metric that counts it as a hit
    would have let that ship."""
    from bench.planted import subsets_agree

    planted = [{"a", "b"}, {"c", "d"}]
    ours_right = [{"a", "b", "f1"}, {"c", "d", "f2"}]
    ours_too_many = [{"a", "b", "f1"}, {"c", "d", "f2"}, {"a", "b", "f2"}, {"c", "d", "f1"}]
    ours_wrong = [{"a", "c", "f1"}, {"b", "d", "f2"}]

    assert subsets_agree(planted, ours_right)
    assert not subsets_agree(planted, ours_too_many)
    assert not subsets_agree(planted, ours_wrong)
    assert not subsets_agree(planted, [])


# --------------------------------------------------------------------------
# throughput and cost — metric 8
# --------------------------------------------------------------------------


def test_time_to_close_is_measured_per_arm(card_index):
    for arm in ("securo_raw", "securo_grouped", "deterministic"):
        card = card_index["A"][arm]
        assert card.elapsed_ns is not None and card.elapsed_ns > 0, arm
        assert card.records_per_second > 0, arm


def test_model_spend_is_absent_rather_than_zero(card_index):
    """Same discipline as the absent arm. Nothing called a model, so the cost
    of calling one is unknown — not zero."""
    card = card_index["A"]["deterministic"]
    assert card.model_spend_paise is None
    assert "absent" in card.cost_line()
    assert "0.00" not in card.cost_line()


# --------------------------------------------------------------------------
# nothing is dropped before the accountability boundary
# --------------------------------------------------------------------------


def test_every_bank_record_is_an_anchor_or_out_of_scope_with_a_reason(closes):
    """Found while building metric 5: the runner filtered the bank side down to
    gateway credits *before* the completeness audit could see it, so records
    left the pipeline with no disposition and invariant 8 still read `complete`.
    A filter upstream of the accountability boundary is the exact shape this
    build keeps finding."""
    result = closes["A"]
    disposed = set(result.completeness.anchors) | set(result.scope)
    assert {r.record_id for r in result.bank_records} <= disposed
    assert all(reason.strip() for reason in result.scope.values())


def test_the_planted_missing_remittance_reaches_the_engine(closes):
    """`bl_00023` is a credit with nothing behind it — the planted `E08`, and
    the single most interesting line on a bank statement. It was being dropped
    by the anchor filter for carrying no gateway key, which is what makes it
    interesting."""
    result = closes["A"]
    anchor_ext = {result.external_of[r] for r in result.completeness.anchors}
    assert "bl_00023" in anchor_ext, "the unattributable credit never reached the engine"
    assert result.completeness.complete


def test_out_of_scope_is_reported_not_merely_recorded(capsys):
    """Shrinking the problem must be visible on the page. A scope declaration
    nobody prints is a silent filter with extra steps."""
    from bench.run import main

    main(["--batch", "A"])
    out = capsys.readouterr().out
    assert "out of scope" in out.lower()


# --------------------------------------------------------------------------
# measurement rests on inputs that were checked
# --------------------------------------------------------------------------


def test_eval_verifies_its_inputs_before_measuring():
    from bench.generator import verify_manifest

    assert verify_manifest(BATCHES) == [], "batches on disk do not match the committed manifest"


def test_a_tampered_batch_is_refused_rather_than_measured(tmp_path):
    """'From a clean checkout' is only a claim unless the bytes are checked.
    Regenerating on every run would hide a tamper by overwriting it, so the
    manifest is verified after generation, not instead of it."""
    import shutil

    from bench.generator import verify_manifest

    shutil.copytree(BATCHES, tmp_path / "b")
    target = tmp_path / "b" / "A" / "settlement.csv"
    target.write_text(target.read_text() + "\n")
    mismatches = verify_manifest(tmp_path / "b")
    assert any("settlement" in m for m in mismatches), mismatches


def test_a_missing_file_is_a_mismatch_not_a_pass(tmp_path):
    import shutil

    from bench.generator import verify_manifest

    shutil.copytree(BATCHES, tmp_path / "b")
    (tmp_path / "b" / "A" / "orders.csv").unlink()
    assert any("orders" in m for m in verify_manifest(tmp_path / "b"))


# --------------------------------------------------------------------------
# the run fails loudly
# --------------------------------------------------------------------------


def test_the_runner_exits_non_zero_when_a_close_is_incomplete(monkeypatch):
    """A scorecard printed by a run that could not account for its inputs is
    worse than no scorecard."""
    import bench.run as run_mod

    real = run_mod.close

    def broken(batch, **kw):
        result = real(batch, **kw)
        return result.__class__(**{**result.__dict__, "ok": False})

    monkeypatch.setattr(run_mod, "close", broken)
    assert run_mod.main([]) != 0


def test_blocking_recall_is_printed_above_the_rates(capsys):
    """Invariant 6, unchanged from P4 and re-asserted here because P10 rewrites
    the renderer."""
    from bench.run import main

    main(["--batch", "A"])
    out = capsys.readouterr().out
    assert "blocking recall" in out
    assert out.index("blocking recall") < out.index("auto-match")


def test_batch_b_is_measured_and_agrees_with_a(card_index):
    """B is held out. It is measured on every run so a change that only works
    on the batch we developed against is visible immediately."""
    for arm in ("securo_grouped", "deterministic"):
        a, b = card_index["A"][arm], card_index["B"][arm]
        assert a.auto_match_rate.value == pytest.approx(b.auto_match_rate.value, abs=0.02), arm


# --------------------------------------------------------------------------
# the branches coverage found unexercised — an uncounted counter is a proxy
# --------------------------------------------------------------------------


def test_the_clean_checkout_path_generates_and_still_verifies(tmp_path):
    """'From a clean checkout' was the gate sentence and the line that makes it
    true had never run: every test so far measured batches that were already on
    disk. A clean checkout has the committed manifest and no data."""
    import shutil

    from bench.run import prepare_inputs

    shutil.copy(BATCHES / "MANIFEST.json", tmp_path / "MANIFEST.json")
    assert not (tmp_path / "A").exists()

    assert prepare_inputs(tmp_path) == []
    assert (tmp_path / "A" / "settlement.csv").exists()
    assert (tmp_path / "B" / "labels.json").exists()


def test_generation_does_not_get_to_rewrite_the_record_it_is_checked_against(tmp_path):
    """The generator writes a manifest from the bytes it just produced. Verify
    against *that* and the batches are compared with themselves — audit finding
    `F1` in a third costume. The committed manifest is restored first, so a
    generator that drifts is caught rather than endorsed."""
    import json
    import shutil

    from bench.run import prepare_inputs

    manifest = json.loads((BATCHES / "MANIFEST.json").read_text())
    manifest["A"]["files"]["settlement"] = "0" * 64
    (tmp_path / "MANIFEST.json").write_text(json.dumps(manifest))

    problems = prepare_inputs(tmp_path)
    assert any("settlement" in p for p in problems), (
        "generation overwrote the committed manifest — verification became circular"
    )
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_the_runner_prints_no_numbers_over_unverified_inputs(monkeypatch, capsys):
    import bench.run as run_mod

    monkeypatch.setattr(run_mod, "prepare_inputs", lambda *a, **k: ["A/settlement: sha256 ..."])
    assert run_mod.main([]) == 2
    out = capsys.readouterr().out
    assert "REFUSING" in out
    assert "auto-match" not in out, "a scorecard was printed over inputs nobody verified"


def test_a_wrong_match_is_actually_counted_as_a_false_match():
    """The false-match rate is the number this project says matters most, and
    the branch that increments it had never executed — every arm on this corpus
    is correct. A 0.00% produced by a counter that has never counted is not a
    measurement."""
    from bench.arms import ArmResult
    from bench.metrics import score

    truth = {"bl_1": frozenset({"a", "b"})}
    wrong = ArmResult(name="x", pairs={"bl_1": frozenset({"a", "c"})}, tiers={"T0": 1})
    card = score(wrong, truth)
    assert card.false_matches == 1
    assert card.correct == 0
    assert card.false_match_rate.value == 1.0
    assert "1/1" in str(card.false_match_rate)


def test_a_match_the_verifier_refuses_never_reaches_the_scorecard(monkeypatch):
    """`deterministic.run` claims an unverified match is not a match. Nothing
    had ever taken that branch, so the claim was untested code. It also pins the
    tier split to what is *reported*: a refused match must leave both numbers."""
    import bench.arms.deterministic as arm
    from bench.metrics import score
    from bench.run import SETTLEMENT_3WAY, SETTLEMENT_POLICY, load_sides, truth_pairs

    import recon.close as close_mod
    from recon.engine.verifier import Verdict, VerdictKind

    sides = load_sides("A")
    monkeypatch.setattr(
        close_mod,
        "verify",
        lambda *a, **k: Verdict(VerdictKind.REFUTED, None, ["mutation"], "settlement-in@v1"),
    )
    result = arm.run(
        sides.bank,
        sides.settlement,
        SETTLEMENT_3WAY,
        SETTLEMENT_POLICY,
        sides.provenance,
        None,
        sides.scope,
    )
    assert result.pairs == {}
    assert result.tiers == {}
    assert any("refused by the verifier" in n for n in result.notes)
    card = score(result, truth_pairs(BATCHES / "A" / "labels.json"))
    assert card.produced == 0


def test_securo_date_window_admits_and_excludes(monkeypatch):
    """The baseline's fairness rests on its date window working. On this corpus
    the exact-amount bucket almost never collides, so neither the window nor the
    already-taken branch ever fires — the transcription is load-bearing and was
    unexercised. P3 already found one way to handicap this baseline by a date
    choice; this stops a second."""
    from datetime import timedelta

    from bench.arms import securo_baseline

    from recon.contracts import Record

    def rec(rid, side, day):
        return Record(
            record_id=rid,
            side=side,
            source="s",
            row_ordinal=0,
            posted_on=date(2026, 8, 10) + timedelta(days=day),
            amount=D("100.00"),
            currency="INR",
            doc_hash="h" * 8,
        )

    anchor = [("bl_1", rec("b1", "bank", 0))]
    inside = securo_baseline.run_raw(anchor, [("s_near", rec("r1", "settlement", 2))])
    outside = securo_baseline.run_raw(anchor, [("s_far", rec("r2", "settlement", 3))])
    assert inside.pairs == {"bl_1": frozenset({"s_near"})}
    assert outside.pairs == {}, "a row outside the +/-2 day window must not pair"


def test_a_scorecard_with_no_timing_reports_no_throughput():
    from bench.metrics import Scorecard

    card = Scorecard(arm="x", true_pairs=1, produced=0, records_scored=10)
    assert card.records_per_second == 0
    assert card.elapsed_ms() == 0
    assert "exception list not scored" in card.render_exceptions()


def test_a_real_model_spend_renders_as_money_not_as_absent():
    """The P12 branch. Rendering a cost is not something to first exercise in
    front of a live model."""
    from bench.metrics import Scorecard

    card = Scorecard(arm="x", true_pairs=1, model_spend_paise=5217)
    assert card.cost_line() == "model spend ₹52.17"


def test_an_undefined_rate_is_not_a_zero():
    """Nothing ambiguous planted is not the same as ambiguity we failed to
    detect. `0/0` renders as `n/a`, because zero here would be a claim."""
    from bench.rate import Rate

    empty = Rate(0, 0)
    assert not empty.defined
    assert "n/a" in str(empty)
    assert Rate(0, 5).defined and "0.0%" in str(Rate(0, 5))


def test_securo_pairs_each_row_at_most_once():
    """Its algorithm is strictly 1:1 and the branch enforcing that never fires
    on this corpus — exact-amount buckets rarely collide. Transcribed behaviour
    nothing exercises is behaviour we have assumed, not reproduced."""
    from bench.arms import securo_baseline

    from recon.contracts import Record

    def rec(rid, side):
        return Record(
            record_id=rid,
            side=side,
            source="s",
            row_ordinal=0,
            posted_on=date(2026, 8, 10),
            amount=D("100.00"),
            currency="INR",
            doc_hash="h" * 8,
        )

    anchors = [("bl_1", rec("b1", "bank")), ("bl_2", rec("b2", "bank"))]
    one_row = [("s_1", rec("r1", "settlement"))]
    result = securo_baseline.run_raw(anchors, one_row)
    assert result.pairs == {"bl_1": frozenset({"s_1"})}, (
        "one settlement row backed two bank lines — securo pairs 1:1"
    )
