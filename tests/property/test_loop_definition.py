"""A loop the product can run on its own, and cannot be talked into widening.

`recon.loop` exists because `src/recon/` could reconcile and could not *read*:
which adapter opens which file lived in `bench/run.py`, so the only executable
form of "close the books" was a benchmark. Any surface built over that would
either import the harness that scores against ground truth or grow a second copy
of intake — and a second copy of intake is the banned pattern, a demo path that
differs from the real path.

What is asserted here is mostly about what the boundary refuses. A loop run is
the entry point an HTTP request and an MCP tool call both reach, and the MCP
caller may be a model, so "no authority through this door" has to be structural.
"""

from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path

import pytest

from recon import loop as looplib
from recon.profiles import settlement

BATCHES = Path("data/batches")


def test_the_loop_reads_its_own_sources():
    lp = looplib.get("settlement_3way")
    loaded = lp.load(BATCHES / "A")
    assert loaded.anchor_rows and loaded.group_rows
    assert loaded.scope, "a loop that declares nothing out of scope is not disposing of debits"
    assert all(reason.strip() for reason in loaded.scope.values()), "a bare exclusion"


def test_the_benchmark_and_the_product_load_the_same_rows():
    """One implementation of intake, asserted rather than agreed by inspection."""
    from bench.run import load_sides

    theirs = load_sides("A")
    ours = settlement.load_sources(BATCHES / "A")
    assert [r.record_id for _, r in theirs.bank] == [r.record_id for _, r in ours.anchor_rows]
    assert [r.record_id for _, r in theirs.settlement] == [r.record_id for _, r in ours.group_rows]
    assert theirs.scope == ours.scope
    assert theirs.digests == ours.digests


def test_no_row_is_dropped_before_the_completeness_audit_can_see_it():
    """The benchmark's version discarded group rows whose source gave them no id.

    It never fired on these batches — a filter over an empty set is invisible —
    but it sat *before* invariant 8's audit, which is a silent drop with extra
    steps. Nothing is filtered now; a row with no source id is shown under its
    record id.
    """
    lp = looplib.get("settlement_3way")
    loaded = lp.load(BATCHES / "A")
    for external, record in loaded.group_rows:
        assert external, f"{record.record_id} reached the close with no name at all"
    assert len(loaded.group_rows) == len({r.record_id for _, r in loaded.group_rows})

    source = inspect.getsource(settlement.load_sources)
    assert "if rec.source_row_id" not in source, (
        "a filter on source_row_id is back in the loader, ahead of the audit"
    )


def test_a_run_takes_no_authority():
    """`F1` and `F2` both reduce to "the caller supplied its own permission", and
    a parameter is how a caller supplies anything.

    Checked on the signature, because this is the function a surface calls and
    an unused parameter today is a used one after the next refactor.
    """
    banned = {"policy", "taxonomy", "rules", "chart", "tolerance", "profile", "side_signs"}
    taken = set(inspect.signature(looplib.run).parameters)
    assert not (banned & taken), f"recon.loop.run accepts authority: {sorted(banned & taken)}"
    # `track` is a progress sink and `label`/`runs_dir` are where to write. None
    # of them can change what a close is *permitted* to accept, which is the only
    # question this test asks — the exhaustive set is here so a parameter that
    # could has to be argued for rather than added.
    assert taken == {"loop", "root", "runs_dir", "label", "track"}, taken


def test_a_half_arrived_period_is_refused_rather_than_closed(tmp_path: Path):
    """A close over a period missing a source would report a clean month over
    rows that never came."""
    lp = looplib.get("settlement_3way")
    (tmp_path / "settlement.csv").write_text("row_id\n")
    assert lp.missing(tmp_path) == ["bank_icici_camt053.xml"]
    with pytest.raises(looplib.LoopError) as caught:
        looplib.run(lp, tmp_path)
    assert "bank_icici_camt053.xml" in str(caught.value)


def test_a_period_is_listed_only_when_every_source_has_arrived(tmp_path: Path):
    lp = looplib.get("settlement_3way")
    (tmp_path / "JAN").mkdir()
    (tmp_path / "JAN" / "settlement.csv").write_text("row_id\n")
    assert looplib.source_sets(lp, tmp_path) == []
    assert looplib.source_sets(lp, BATCHES) == ["A", "B"]


def test_an_unknown_loop_is_a_configuration_error_not_a_default():
    with pytest.raises(looplib.LoopError):
        looplib.get("gstr2b")


# --------------------------------------------------------------- the run id


def test_the_run_id_is_derived_from_the_inputs_and_the_authority():
    """Content-derived, so re-closing identical inputs is idempotent rather than
    a second record of one event — and a changed input gets its own record
    instead of overwriting the old one."""
    lp = looplib.get("settlement_3way")
    a = lp.load(BATCHES / "A")
    b = lp.load(BATCHES / "B")

    assert looplib.run_id_for(lp, a, label="A") == looplib.run_id_for(lp, a, label="A")
    assert looplib.run_id_for(lp, a, label="A") != looplib.run_id_for(lp, b, label="B")
    assert looplib.run_id_for(lp, a, label="A") != looplib.run_id_for(lp, b, label="A"), (
        "different source bytes produced the same run id — a close would overwrite another"
    )


def test_changing_the_authority_changes_the_run_id():
    """Two closes over the same bytes under different rules are two different
    closes, and must not share a record."""
    from recon.contracts.rule import ActionKind, Predicate, Rule, RuleAction

    lp = looplib.get("settlement_3way")
    loaded = lp.load(BATCHES / "A")
    rule = Rule(
        rule_id="R-X",
        profile=lp.name,
        when=[Predicate(field="amount", op="gt", value="0")],
        then=[RuleAction(kind=ActionKind.SUPPRESS, reason="x")],
    )
    assert looplib.run_id_for(lp, loaded, label="A") != looplib.run_id_for(
        lp, loaded, label="A", rules=[rule]
    )


def test_the_run_id_does_not_move_on_its_own():
    """No wall clock. A timestamped id would make a re-run of identical inputs
    look like new information, which is the whole reason `outcome_digest`
    excludes timing too."""
    source = inspect.getsource(looplib.run_id_for) + inspect.getsource(looplib.run)
    for banned in ("datetime.now", "time.time", "uuid", "random"):
        assert banned not in source, f"{banned} in a run id makes a close unrepeatable"


def test_the_period_belongs_to_the_loop_not_to_a_batch():
    lp = looplib.get("settlement_3way")
    assert lp.period == (settlement.WINDOW[0], settlement.WINDOW[1])
    assert lp.profile.tolerance.absolute == Decimal("0.50")


def test_a_period_belongs_to_one_loop(tmp_path):
    """A directory holding none of a loop's files is not that loop's period.

    Without this every loop listed every directory, so the settlement screen
    reported `FY2627` as "missing bank_icici_camt053.xml" and the tax screen
    reported `A` as "missing form26as.txt" — each statement true, and each of
    them nonsense, because neither period was ever a candidate. Six rows on a
    page where there are three periods, four of them un-closeable by
    construction.
    """
    import shutil

    from recon import loop as looplib

    root = tmp_path / "sources"
    root.mkdir()
    for name in ("A", "B", "FY2627"):
        shutil.copytree(f"data/batches/{name}", root / name)

    looplib._install()
    settlement = looplib.get("settlement_3way")
    tds = looplib.get("tds_26as")

    assert looplib.source_sets(settlement, root) == ["A", "B"]
    assert looplib.source_sets(tds, root) == ["FY2627"]

    # And the *incomplete* listing, which is what the screens render, must be
    # scoped the same way — a period is listed when it is short a file, and not
    # when it was never this loop's.
    assert {d.name for d in looplib.periods(settlement, root)} == {"A", "B"}
    assert {d.name for d in looplib.periods(tds, root)} == {"FY2627"}


def test_a_half_arrived_period_is_still_this_loops_period(tmp_path):
    """Scoping must not hide the case it exists to surface.

    "Where is October?" answered with silence is the same failure as a filter
    before the completeness audit. A period missing *one* of its two files is
    this loop's period and has to stay on the list, named for what it lacks.
    """
    import shutil

    from recon import loop as looplib

    root = tmp_path / "sources"
    (root / "October").mkdir(parents=True)
    looplib._install()
    settlement = looplib.get("settlement_3way")

    shutil.copy(
        "data/batches/A/bank_icici_camt053.xml", root / "October" / "bank_icici_camt053.xml"
    )

    assert looplib.source_sets(settlement, root) == [], "a half-arrived period is closeable"
    assert {d.name for d in looplib.periods(settlement, root)} == {"October"}
    assert settlement.missing(root / "October") == ["settlement.csv"]
