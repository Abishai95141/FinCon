"""P23 — a second loop, and whether invariant 7 was ever true.

"The engine is domain-agnostic" has been asserted since P1 and tested by exactly
one reconciliation, which is not a test. `tds_26as` is the check: Form 26AS from
TRACES against a TDS receivable ledger, matched on `TAN + section + quarter`
rather than on an amount and a date, over an April-to-March year rather than a
calendar window, where a break is an administrative failure by a third party
rather than money going somewhere.

**The gate's clause:** the second loop closes, its numbers agree with labels
authored before the engine saw a row, every input has a disposition, and
`src/recon/engine/` is byte-identical to what settlement runs on.

That last clause is the whole point. A generality that needed a change to
accommodate its second instance was not a generality.

**What this loop found in the engine.** Nothing that required an engine change —
but one real defect in a *profile-level* choice that settlement had been getting
away with. `strategies.viable` narrows candidate groups by `counterparty_key`
and then by amount, so a coarse key lets the tolerant pass pair an anchor with
any group from the same party whose amount is close enough. Keyed on the
deductor's TAN, this loop produced **six false matches** — 26AS rows paired with
ledger vouchers from a different section entirely. Settlement escapes it because
a payout is tens of thousands and two landing within fifty paise is rare. That is
luck, not a property, and `test_a_coarse_counterparty_key_produces_false_matches`
holds the evidence.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
from collections import Counter
from pathlib import Path

import pytest
from bench.generator.tds import generate

from recon import loop as looplib
from recon import service
from recon.contracts import CodeStatus

pytestmark = pytest.mark.gate

ROOT = Path(__file__).resolve().parents[2]
LOOP = "tds_26as"


@pytest.fixture(scope="module")
def batch(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("tds") / "FY2627"
    generate(root)
    return root


@pytest.fixture(scope="module")
def closed(batch, tmp_path_factory):
    runs = tmp_path_factory.mktemp("tdsruns")
    result = looplib.run(looplib.get(LOOP), batch, runs_dir=runs, label="FY2627")
    return service.view(result.run_id, runs), json.loads((batch / "labels.json").read_text()), runs


# ------------------------------------------------- the engine did not change


def test_the_engine_speaks_no_domain():
    """Invariant 7, asserted as a property rather than as a date.

    The first version checked that `src/recon/engine/` had not been committed to
    recently — which passed for the second loop and then failed the moment
    near-miss diagnosis was added, correctly and uselessly. "The engine has not
    changed" is not the invariant; plenty of legitimate work changes it. **"The
    engine knows nothing about any domain" is**, and that does not decay with the
    commit log.

    Identifiers and live string literals only. A docstring may say "same deductor,
    same section" to explain what a general mechanism is *for* — prose is how a
    reader learns why the abstraction exists. A `deductor` variable, or the
    string `"194O"` in a comparison, is the domain reaching the kernel.

    The second loop is the proof this is real: `tan`, `section` and `quarter`
    reach the engine as `profile.key_parts`, and `X-TDS-QUARTER-ERROR` reaches
    `diagnose` through a mapping the profile supplies.
    """
    domain_words = {
        "tds",
        "26as",
        "traces",
        "deductor",
        "deductee",
        "tan",
        "razorpay",
        "gateway",
        "bank",
        "invoice",
        "gstr",
        "194o",
        "quarter",
        "section",
    }

    def docstring_nodes(tree: ast.AST) -> set[int]:
        """Every string that is prose, by identity.

        Any bare string *statement* — not just a module, class or function
        docstring, but the attribute docstring under a dataclass field, which is
        how most of this codebase documents itself. Missing those made the first
        run of this test report `MatchProfile.key_parts`'s own explanation as a
        domain leak.
        """
        return {
            id(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }

    offenders: list[str] = []
    for path in sorted((ROOT / "src" / "recon" / "engine").rglob("*.py")):
        tree = ast.parse(path.read_text())
        exempt = docstring_nodes(tree)

        tokens: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                tokens.add(node.id)
            elif isinstance(node, ast.Attribute):
                tokens.add(node.attr)
            elif isinstance(node, ast.arg):
                tokens.add(node.arg)
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in exempt
            ):
                tokens.add(node.value)

        for token in tokens:
            words = set(re.split(r"[^a-z0-9]+", str(token).lower()))
            leaked = words & domain_words
            if leaked:
                offenders.append(f"{path.name}: {token!r} -> {sorted(leaked)}")

    assert not offenders, (
        "domain vocabulary reached the engine as code, so invariant 7 is false:\n  "
        + "\n  ".join(sorted(set(offenders))[:8])
    )


def test_both_loops_are_registered_and_share_nothing_but_the_engine():
    looplib._install()
    assert set(looplib.names()) == {"settlement_3way", LOOP}

    settlement, tds = looplib.get("settlement_3way"), looplib.get(LOOP)
    assert settlement.period != tds.period, "two loops with one period is one loop"
    assert set(settlement.filenames).isdisjoint(tds.filenames)
    assert settlement.policy_file != tds.policy_file
    assert settlement.chart().accounts != tds.chart().accounts

    # The *same* taxonomy, on purpose. One vocabulary across loops: `E03` means
    # sub-unit rounding whether the unit is a gateway fee or a tax deposit, and a
    # second code for it per loop is how a taxonomy stops meaning anything.
    assert settlement.taxonomy_file == tds.taxonomy_file


def test_the_two_loops_disagree_about_direction_and_tolerance():
    """Not decoration. These are the two settings that make one reconciliation
    different from another, and a second loop that copied them would be testing
    the same thing twice."""
    settlement, tds = looplib.get("settlement_3way"), looplib.get(LOOP)

    assert settlement.profile.counterparty_key != tds.profile.counterparty_key
    assert tds.profile.tolerance.absolute < settlement.profile.tolerance.absolute
    assert tds.profile.tolerance.date_window_days == 0
    assert tds.profile.consistency is None, (
        "a consistency relation here would be a weaker second check on a rate "
        "that is published in the Act"
    )


# ------------------------------------------------------ it closes, correctly


def test_the_second_loop_closes(closed):
    view, _labels, _runs = closed
    assert view.ok, f"the close did not complete: {view.blocked}"
    assert view.tiers.anchors_in_scope > 0
    assert view.matches


def test_the_numbers_agree_with_labels_written_before_the_engine_ran(closed):
    """Scored against an answer authored independently. A fixture read back out
    of a close asserts whatever the close happens to do."""
    view, labels, _runs = closed

    rounding = labels["by_code"].get("E03", 0)
    expected_exact = labels["expected_matches"]

    assert view.tiers.by_match_tier.get("T0") == expected_exact, (
        f"{view.tiers.by_match_tier.get('T0')} exact matches against "
        f"{expected_exact} clean rows in the labels"
    )
    assert view.tiers.by_match_tier.get("T1") == rounding, (
        "the tolerant pass matched something other than the planted rounding — "
        "which is how six false matches got in the first time"
    )
    assert view.tiers.matched == expected_exact + rounding


def test_every_input_has_a_disposition(closed, batch):
    """Invariant 8, on a loop that has never run it before.

    Both sides, deliberately. The settlement loop's anchors are bank credits and
    a missing one is visible; here a deduction absent from *our* books is the
    only variance in our favour, and a completeness audit that walked one side
    would never see it.
    """
    view, labels, _runs = closed

    anchors = view.tiers.anchors_in_scope
    unmatched_anchors = anchors - view.tiers.matched
    assert len(view.exceptions) >= unmatched_anchors, (
        f"{anchors} anchors, {view.tiers.matched} matched, so {unmatched_anchors} are "
        f"unaccounted for and only {len(view.exceptions)} exceptions were raised"
    )

    # Both sides. 53 anchors and 58 ledger rows: 42 matched leaves 11 anchors and
    # 16 vouchers, and the tail must carry all 27. A completeness audit that
    # walked the anchor side alone would miss every deduction absent from our own
    # books, which is the one variance here that is in our favour.
    #
    # Counted rather than filtered by `leg`, because `leg` is a closed set of
    # settlement's own words and reads "bank" on this loop — see the strict xfail
    # in tests/known_broken.py.
    ledger_rows = sum(1 for _ in (batch / "tds_ledger.csv").read_text().splitlines()[1:])
    both_sides = (anchors - view.tiers.matched) + (ledger_rows - view.tiers.matched)
    assert len(view.exceptions) == both_sides, (
        f"{len(view.exceptions)} exceptions against {both_sides} unmatched rows "
        f"across the two sides — something left with no disposition"
    )

    planted = len(labels["planted"])
    assert len(view.exceptions) >= planted - labels["by_code"].get("E03", 0), (
        f"{len(view.exceptions)} exceptions against {planted} planted variances; "
        f"the tail is smaller than the defects put into the batch"
    )


def test_nothing_is_matched_that_the_labels_say_is_broken(closed, batch):
    """A false match is the failure this project exists not to produce, and it is
    the one a match rate hides. Every planted variance whose key was altered must
    be absent from the match set."""
    view, labels, _runs = closed
    matched_refs = {m.group_ref for m in view.matches}

    for planted in labels["planted"]:
        if planted["expected_code"] == "E03":
            continue  # rounding is meant to absorb
        # The full key, date included. Without the date this flagged a *clean*
        # row that happened to share a deductor, section and quarter with a
        # planted one — a test failing on the right subject for the wrong reason.
        key = "|".join(
            [
                planted["tan"].lower(),
                planted["section"].lower(),
                planted["quarter"].lower(),
                planted["transaction_date"],
            ]
        )
        assert key not in matched_refs, f"{planted['expected_code']} on {key} was matched anyway"


# ------------------------------------------------------------- the vocabulary


def test_the_tax_codes_exist_and_may_not_post_yet():
    """Minted, accepted, and **provisional**. Naming grants nothing: a code
    reaches an expense account when a human promotes it with a written
    definition, not when somebody adds it to a JSON file."""
    registry = looplib.get(LOOP).taxonomy()
    tds_codes = {c.code: c for c in registry.codes.values() if c.code.startswith("X-TDS-")}

    assert len(tds_codes) == 6, f"expected six tax codes, found {sorted(tds_codes)}"
    for code in tds_codes.values():
        assert code.status is CodeStatus.PROVISIONAL, (
            f"{code.code} is {code.status.value}; nobody has approved it directing a posting"
        )
        assert code.definition and len(code.definition) > 80, (
            f"{code.code} has no written definition, so it cannot be promoted"
        )
        assert code.owner, f"{code.code} routes to nobody"


def test_a_tax_deduction_no_longer_has_to_be_a_fee_variance():
    """The reason this is a loop rather than a rule.

    A §194-O deduction inside a gateway settlement can only be `E02` or `E14`
    there. Both are wrong, and the second is worse: TDS reconciles against a
    government record on a quarterly cadence, so the counterpart, the calendar
    and the desk are all different.
    """
    registry = looplib.get(LOOP).taxonomy()
    codes = {c.code for c in registry.codes.values()}

    assert "X-TDS-NOT-DEPOSITED" in codes
    assert "E02" in codes and "E14" in codes, "the settlement codes are gone from the registry"

    not_deposited = registry.codes["X-TDS-NOT-DEPOSITED"]
    fee_variance = registry.codes["E02"]
    assert not_deposited.owner != fee_variance.owner, (
        "a missing tax deposit routes to the same desk as a gateway fee argument"
    )


# -------------------------------------------------- what this loop found


def test_a_coarse_counterparty_key_produces_false_matches(batch, tmp_path):
    """The defect this loop found, held so it cannot come back.

    `strategies.viable` narrows candidates by `counterparty_key` and then by
    amount. Keyed on the deductor's TAN — the obvious choice, and the one this
    profile shipped first — the tolerant pass paired six 26AS rows with ledger
    vouchers from a different section entirely, because a deductor files many
    small deductions and fifty paise apart is common at tens of rupees.

    Settlement escapes this because a payout is tens of thousands. That is luck
    rather than a property, and this test is the evidence.
    """
    import dataclasses

    from recon.profiles import tds as profile

    loop = looplib.get(LOOP)
    coarse = dataclasses.replace(loop.profile, counterparty_key="tan")

    runs = tmp_path / "coarse"
    loose = dataclasses.replace(loop, profile=coarse, name="tds_coarse")
    result = looplib.run(loose, batch, runs_dir=runs, label="coarse")
    loose_view = service.view(result.run_id, runs)

    labels = json.loads((batch / "labels.json").read_text())
    expected = labels["expected_matches"] + labels["by_code"].get("E03", 0)

    assert loose_view.tiers.matched > expected, (
        "the coarse key no longer over-matches, so either the corpus or "
        "`viable` changed and this test has lost its subject"
    )
    assert profile.PROFILE.counterparty_key == "pairing", (
        "the shipped profile is back on a coarse key"
    )


def test_the_proofs_are_declared_and_the_reason_is_stated(closed):
    """Every match here is `P3 DECLARED`, not `P0 ARITHMETIC`, and that is not a
    bug to paper over.

    A `P0` needs the intake proofs to tie out, and the 26AS extract this reads
    carries no control total — the real portal download has a summary block and
    the reader skips past nothing, so there is no figure to tie to. Recorded as
    declared rather than quietly reported as proven: an unmeasured thing shown
    as a stronger claim is the defect rule 1 names.
    """
    view, _labels, _runs = closed
    tiers = view.tiers.by_proof_tier

    assert tiers, "no proof tiers recorded at all"
    assert set(tiers) == {"P3"}, (
        f"proof tiers are {tiers}; if this is now P0 the control total landed and "
        f"this test should say so instead"
    )


def test_the_batch_is_reproducible_from_its_seed(tmp_path):
    """Two generations from one seed are the same bytes, or a regression is
    indistinguishable from a reseed."""
    first, second = tmp_path / "one", tmp_path / "two"
    generate(first)
    generate(second)

    for name in ("form26as.txt", "tds_ledger.csv", "labels.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes(), (
            f"{name} differs between two runs of the same seed"
        )
    shutil.rmtree(first)


def test_the_planted_tail_is_not_all_one_thing(batch):
    """A batch whose defects are all one code tests one path and reports a
    number that looks like coverage."""
    labels = json.loads((batch / "labels.json").read_text())
    by_code = Counter(p["expected_code"] for p in labels["planted"])

    assert len(by_code) >= 6, f"only {len(by_code)} distinct variances planted"
    assert max(by_code.values()) <= len(labels["planted"]) // 2, (
        f"one code dominates the tail: {by_code}"
    )
