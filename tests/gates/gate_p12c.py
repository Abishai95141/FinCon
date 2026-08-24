"""Gate P12, part 3 — adapter-spec synthesis.

The gate's other half: *drop a source in a format never seen and watch it
author, verify and ingest without configuration.*

`data/batches/*/settlement_psp_v2.csv` is the same 517 settlement movements in a
format nothing has a spec for — semicolon delimiter, two comment lines before
the header, renamed columns, `DD.MM.YYYY` dates and amounts in minor units. It is
generated from the same rows as `settlement.csv`, so correctness is checkable by
**cross-format agreement** rather than by reading the spec: two formats
describing the same account must yield the same records, which is the check P2
already runs for CSV against CAMT.

**What this file asserts is not "the model succeeds".** On the run it was
written against, the model got the structure right — delimiter, header line,
minor units, the non-ISO date — and the *semantics* wrong: `merchant_batch`
became a match key instead of the payout grouping, so every record came back
with `group_ref = None`.

And the five ingest proofs did **not** catch it. They could not: this source
carries no control total and no balances, so the substantive checks skip and the
intake is `declared`, not `verified`. That is build-plan problem `P4` behaving
exactly as designed — and it is the concrete argument for first-use approval,
which until now was a field with a rationale and no demonstration.

So the gate is about the *disposition* of a wrong spec, not the correctness of a
right one.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

pytestmark = pytest.mark.gate

BATCHES = Path("data/batches")
NOVEL = BATCHES / "A" / "settlement_psp_v2.csv"
WINDOW = (date(2026, 7, 1), date(2026, 10, 31))
KEY = os.environ.get("DEEPSEEK_API_KEY")


@pytest.fixture(autouse=True)
def _preconditions(request):
    """Fails loudly for tests that reach a model, and gets out of the way for
    the ones that do not.

    Was module-scoped and unconditional, so half this file — the closed parse
    vocabulary, the producer table, the AST guard keeping model-authored text
    out of the posting layer — ran only when someone had a key and chose to pay
    for a run. Four of those assertions were stale by 2026-08-24.
    """
    if not (BATCHES / "A" / "labels.json").exists():
        pytest.skip("run `make gen` first")
    if request.node.get_closest_marker("live") and not KEY:
        pytest.fail("DEEPSEEK_API_KEY is not set — P12 has no offline mode (CLAUDE.md rule 1)")


@pytest.fixture(scope="module")
def authored():
    """One authoring pass. Module-scoped because it costs a call, and because
    every assertion below is about the same spec."""
    from recon.triage.client import ModelEdge
    from recon.triage.normalize import author_spec

    return author_spec(source="psp-v2", side="settlement", path=NOVEL, edge=ModelEdge())


@pytest.fixture(scope="module")
def known_good():
    from recon.intake import ingest, load_spec

    return ingest(load_spec("gateway-settlement"), BATCHES / "A" / "settlement.csv", WINDOW)


def _rows(result):
    return sorted((r.source_row_id, str(r.amount), r.group_ref) for r in result.records)


# --------------------------------------------------------------------------
# it authors, and what it authors is data
# --------------------------------------------------------------------------


def test_a_spec_is_authored_for_a_format_with_no_configuration(authored):
    assert authored.spec is not None, authored.refusals
    assert authored.reasoning


def test_the_structure_of_an_unseen_file_is_read(authored, capsys):
    """The parts that have to work for any of this to be interesting — the model
    sees twelve raw lines and no schema.

    `header_row` is **reported, not asserted**. Across the runs this was written
    against it came back 3, 3 and 4, and pinning it would make the gate flaky
    while pinning nothing would hide the instability. What is asserted is the
    consequence, in the test below: a wrong header line is caught.
    """
    spec = authored.spec
    assert spec.reader.delimiter == ";"
    assert spec.currency == "INR"
    parses = {f.source: f.parse.value for f in spec.fields}
    assert parses.get("amount_minor") == "decimal_minor", "minor units not recognised"
    fmts = {f.source: f.fmt for f in spec.fields if f.fmt}
    assert fmts.get("booking_timestamp") == "DD.MM.YYYY", "non-ISO date not recognised"
    print(f"\nauthored header_row={spec.reader.header_row} (correct value is 3)")


def test_a_header_line_off_by_one_is_caught_rather_than_half_read(authored):
    """Why `header_row` does not need asserting.

    Off by one in either direction yields **zero** records and a `failed`
    intake, named by row conservation — the P2 rule that a spec parsing nothing
    is a broken spec, not a weakly-evidenced source. So a model that miscounts
    the preamble produces a loud refusal, never a silent partial read.
    """
    from recon.intake import ingest, load_spec

    base = load_spec("novel-psp")
    for header_row, expected in ((2, 0), (3, 517), (4, 0)):
        spec = base.model_copy(
            update={"reader": base.reader.model_copy(update={"header_row": header_row})}
        )
        result = ingest(spec, NOVEL, WINDOW)
        assert len(result.records) == expected, header_row
        if expected == 0:
            assert result.proof.strength == "failed"
            assert "row_conservation" in {c.name for c in result.proof.failed}

    # And the authored spec lands on one side of that line or the other.
    outcome = ingest(authored.spec, NOVEL, WINDOW)
    assert outcome.ok or outcome.proof.failed, "neither ingested nor named a failure"


def test_the_spec_cannot_name_its_own_author_or_approve_itself(authored):
    """Audit finding `F1`'s shape. A spec that could declare itself
    human-authored would walk past first-use approval."""
    assert authored.spec.authored_by == "deepseek-v4-flash"
    assert authored.spec.approved_by is None
    assert authored.spec.needs_first_use_approval


def test_no_generated_code_is_executed_anywhere_on_this_path():
    """ADR-001, asserted structurally rather than argued. This is where a model
    first authors something the engine executes."""
    import ast

    banned = {"eval", "exec", "compile", "__import__"}
    for path in (
        Path("src/recon/triage/normalize.py"),
        *sorted(Path("src/recon/intake").rglob("*.py")),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in banned, f"{path}:{node.lineno} {node.func.id}()"


def test_a_verb_outside_the_vocabulary_is_a_validation_error_not_an_attempt():
    from recon.triage.normalize import build_spec

    out = build_spec(
        {
            "currency": "INR",
            "natural_key": ["amount"],
            "delimiter": ",",
            "header_row": 1,
            "fields": [{"to": "amount", "source": "a", "parse": "exec_python"}],
        },
        source="x",
        side="settlement",
        model="m",
    )
    assert out.spec is None
    assert any("not a valid AdapterSpec" in r for r in out.refusals)


# --------------------------------------------------------------------------
# what happens when it is wrong
# --------------------------------------------------------------------------


def test_a_bad_spec_fails_the_source_and_never_the_run(authored):
    """`ingest()` has promised since P2 that it never raises. A spec naming a
    field outside the closed vocabulary broke that on the first authoring run —
    the same class P6 closed for readers and `natural_key` reopened for
    interpretation the day it was added."""
    from recon.intake import ingest, load_spec

    broken = load_spec("novel-psp").model_copy(update={"natural_key": ["key<txn_ref>"]})
    result = ingest(broken, NOVEL, WINDOW)
    assert not result.ok
    assert result.proof.strength == "failed"
    assert result.records == []


def test_the_authored_spec_is_ingested_and_scored_against_the_known_good(authored, known_good):
    """The cross-format check, and the honest outcome.

    If the spec is right the rows are identical. If it is wrong the difference
    is *localised* rather than argued about — and either way this is a
    measurement, not a review.
    """
    from recon.intake import ingest

    if authored.spec is None:
        pytest.fail(f"nothing to ingest: {authored.refusals}")
    result = ingest(authored.spec, NOVEL, WINDOW)

    if not result.ok:
        assert result.proof.failed, "a failed intake must name what failed"
        return

    mine, theirs = _rows(result), _rows(known_good)
    assert len(result.records) == len(known_good.records), (
        f"row count differs: {len(result.records)} vs {len(known_good.records)}"
    )
    disagreements = [(a, b) for a, b in zip(mine, theirs, strict=True) if a != b]
    print(f"\ncross-format: {len(disagreements)} of {len(mine)} rows disagree")
    for a, b in disagreements[:3]:
        print(f"  authored={a}  known-good={b}")


def test_a_source_with_no_redundancy_can_never_be_more_than_declared(authored):
    """**The finding this part of the phase produced.**

    A semantically wrong spec ingested 517 records cleanly. The five proofs did
    not catch it and could not: this source states no control total and carries
    no balances, so roll-forward and tie-out both skip and the strongest honest
    verdict is `declared`.

    That is build-plan `P4` working as designed, and it is the concrete argument
    for first-use approval — which was a field with a rationale and no
    demonstration until a wrong spec walked through intake unchallenged.
    """
    from recon.intake import ingest, load_spec
    from recon.intake.proofs import CheckStatus

    result = ingest(load_spec("novel-psp"), NOVEL, WINDOW)
    assert result.ok
    assert result.proof.strength == "declared"
    assert not result.proof.verified
    for name in ("balance_roll_forward", "control_total"):
        check = next(c for c in result.proof.checks if c.name == name)
        assert check.status is CheckStatus.SKIP, (
            f"{name} ran on a source with no redundancy — then the argument below is wrong"
        )


def test_the_authoring_is_recorded(tmp_path):
    from recon.contracts import EventKind
    from recon.journal import Journal, read
    from recon.triage.client import ModelEdge
    from recon.triage.normalize import author_spec

    journal = Journal(tmp_path / "a.jsonl")
    author_spec(source="psp-v2", side="settlement", path=NOVEL, edge=ModelEdge(), journal=journal)
    events = read(tmp_path / "a.jsonl")
    assert len(events) == 1
    assert events[0].kind in {EventKind.ADAPTER_AUTHORED, EventKind.PROPOSAL_REFUSED}
    assert events[0].actor == "agent:normalize"
    if events[0].kind is EventKind.ADAPTER_AUTHORED:
        assert events[0].payload.needs_approval
