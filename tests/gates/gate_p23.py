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
import textwrap
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
    # **Records**, not exceptions. Since the two sides of one break are paired
    # into a single item, the tail is shorter than the number of unmatched rows
    # by design — and counting items here would have made this test fail for the
    # fix rather than for a lost input, which is the failure it exists to catch.
    ledger_rows = sum(1 for _ in (batch / "tds_ledger.csv").read_text().splitlines()[1:])
    both_sides = (anchors - view.tiers.matched) + (ledger_rows - view.tiers.matched)
    carried = {rid for e in view.exceptions for rid in e.exception.record_ids}
    assert len(carried) == both_sides, (
        f"the tail names {len(carried)} records against {both_sides} unmatched rows "
        f"across the two sides — something left with no disposition"
    )
    assert len(view.exceptions) < both_sides, (
        "no two-sided break was paired, so every row is still its own item"
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


# --------------------------------------------------- naming the tail


def _truth(labels: dict, records: dict, exception) -> str | None:
    """What the labels say this exception is, keyed so it cannot be ambiguous.

    **The date is in the key on purpose.** Two planted variances in this batch
    share `(tan, section, quarter)` — a PAN mismatch and a section mismatch on
    the same deductor and quarter — so a lookup without the date silently
    returns whichever was written last. That is how the first measurement of
    this reported the model getting one wrong when the model was right and the
    scoring was ambiguous.
    """
    for record_id in exception.record_ids:
        record = records.get(record_id)
        if record is None:
            continue
        key = (
            record.keys.get("tan", ""),
            record.keys.get("section", ""),
            record.keys.get("quarter", ""),
            record.posted_on.isoformat(),
        )
        for planted in labels["planted"]:
            if (
                planted["tan"].lower(),
                planted["section"].lower(),
                planted["quarter"].lower(),
                planted["transaction_date"],
            ) == key:
                return planted["expected_code"]
    return None


@pytest.fixture(scope="module")
def records(batch):
    src = looplib.get(LOOP).load(batch)
    return {rec.record_id: rec for _, rec in [*src.anchor_rows, *src.group_rows]}


def test_the_arithmetic_names_most_of_the_tail_and_is_never_wrong(closed, records):
    """The half that needs no model, scored against labels written first.

    A derived code is `P0 ARITHMETIC`. Being *mostly* right is not good enough
    for that tier — a wrong code at P0 is worse than `E14`, because nothing
    downstream will question it.
    """
    view, labels, _runs = closed

    derived = [
        e.exception
        for e in view.exceptions
        if e.exception.code != "E14" and e.exception.code_provenance.value == "P0"
    ]
    # Eleven *breaks*: three section, three quarter and three rate errors, each
    # paired across two rows, plus two one-sided unbooked deductions.
    assert len(derived) >= 11, f"only {len(derived)} of the tail was named arithmetically"

    wrong = []
    for exception in derived:
        expected = _truth(labels, records, exception)
        if expected is not None and expected != exception.code:
            wrong.append(f"{exception.exception_id}: said {exception.code}, labels say {expected}")

    assert not wrong, "arithmetic named something wrongly at P0:\n  " + "\n  ".join(wrong)


def test_what_is_left_is_ambiguous_rather_than_merely_hard(closed, records):
    """Every remaining `E14` must be a *stated* ambiguity, not a shrug.

    "Unexplained" was the honest answer when the engine had one row and no
    comparison. Now it has the near miss, so anything still unnamed has to say
    which causes it could be and why the files cannot separate them — otherwise
    the near-miss work bought a longer evidence list and nothing else.
    """
    view, labels, _runs = closed
    leftover = [e.exception for e in view.exceptions if e.exception.code == "E14"]
    assert leftover, "nothing is ambiguous, so this test has lost its subject"

    for exception in leftover:
        assert exception.hypothesis.startswith("either "), (
            f"{exception.exception_id} is E14 with no candidates named: {exception.hypothesis[:80]}"
        )
        # And the truth must be inside the pair it names. An ambiguity that
        # excludes the right answer is worse than no ambiguity at all.
        expected = _truth(labels, records, exception)
        if expected is None:
            continue
        assert expected in exception.hypothesis, (
            f"{exception.exception_id} says {exception.hypothesis[:60]!r} and the "
            f"labels say {expected}, which is not among the candidates"
        )


def test_a_model_is_never_offered_an_answer_the_arithmetic_derived(closed):
    """Rule 2, at the one interface a model drives. A proposal is `P2` at best
    and may not overwrite `P0` — and the refusal happens *before* the call, so
    the model does not get the chance to be wrong and we do not pay for it."""
    from recon.triage.classify import reclassifiable

    view, _labels, _runs = closed
    offered = [e.exception for e in view.exceptions if reclassifiable(e.exception)]

    assert offered, "nothing is offered to triage, so the model does no work at all"
    assert all(e.code == "E14" for e in offered), (
        f"a derived code was offered for reclassification: {sorted({e.code for e in offered})}"
    )


@pytest.mark.live
def test_the_model_declines_what_the_files_cannot_separate(closed, records):
    """The measurement that matters, and it can go either way.

    Seven items reach the model, and every one of them is a ledger row with
    nothing on the government's side — which is *either* tax never deposited or
    tax deposited against another PAN. No amount of reasoning separates those
    from these two files; you find out by asking the deductor.

    So the useful answer is "I cannot tell, and here are the two". A model that
    picks one is right about half the time and confident every time, and the
    wrong half sends a correction return to a deductor who did nothing wrong.

    This asserts the honest behaviour rather than an accuracy number. If a future
    model starts guessing here, that is a regression even if its guesses improve.
    """
    from recon.api.serve import load_dev_env
    from recon.triage.classify import classify, reclassifiable
    from recon.triage.client import ModelEdge

    load_dev_env()
    view, labels, _runs = closed
    exceptions = [e.exception for e in view.exceptions]
    offered = [e for e in exceptions if reclassifiable(e)]
    assert offered, "nothing to ask about"

    loop = looplib.get(LOOP)
    edge = ModelEdge()
    results = classify(exceptions=exceptions, taxonomy=loop.taxonomy(), records=records, edge=edge)
    asked = [
        c
        for c in results
        if c.exception_id in {e.exception_id for e in offered}
        and not any("not offered" in r for r in c.refusals)
    ]
    assert len(asked) == len(offered), (
        f"{len(offered)} items were offered and {len(asked)} reached the model"
    )

    guessed = [c for c in asked if c.code and not c.cannot_separate]
    declined = [c for c in asked if c.cannot_separate]

    assert not guessed, (
        f"the model picked a single code for {len(guessed)} item(s) the evidence "
        f"cannot separate: {[(c.exception_id, c.code) for c in guessed]}"
    )
    assert len(declined) == len(asked)

    # And the pair it names must contain the answer. Declining is only honest if
    # the candidates are right — "I cannot tell between these two" is useless
    # when the truth is a third thing.
    misses = []
    for classification in declined:
        exception = next(e for e in exceptions if e.exception_id == classification.exception_id)
        expected = _truth(labels, records, exception)
        if expected is not None and expected not in classification.cannot_separate:
            misses.append(
                f"{classification.exception_id}: truth {expected}, "
                f"declined between {classification.cannot_separate}"
            )
    assert not misses, "the declined candidates exclude the answer:\n  " + "\n  ".join(misses)


def test_a_guess_is_refused_even_if_the_model_makes_one(closed):
    """The control that does not depend on the model behaving.

    Asked with the evidence in front of it, deepseek-v4-flash declines every one
    of these. Asked on a different day, or by a different model, it might not —
    and the system has to reach the same place either way. A control that works
    because the model happens to co-operate is not a control.

    The engine derived that these files cannot separate two causes. That is
    arithmetic over raw records, so it is `P0`; a proposal is `P2`; and a lower
    tier does not overturn a higher one. The refusal is the same rule this
    project already runs on, applied at the one interface a model drives.
    """
    from recon.triage.classify import check_proposal

    view, _labels, _runs = closed
    index = {e.exception.exception_id: e.exception for e in view.exceptions}
    ambiguous = [e for e in index.values() if e.ambiguous_codes]
    assert ambiguous, "nothing carries a derived ambiguity, so this test has no subject"

    taxonomy = looplib.get(LOOP).taxonomy()
    exception = ambiguous[0]

    for candidate in exception.ambiguous_codes:
        verdict = check_proposal(
            {
                "exception_id": exception.exception_id,
                "code": candidate,
                "hypothesis": "it is obviously this one",
                "evidence": list(exception.record_ids),
            },
            exceptions=index,
            taxonomy=taxonomy,
        )
        assert not verdict.ok, f"a guess of {candidate} was accepted over a derived ambiguity"
        assert "P0" in " ".join(verdict.reasons)

    declined = check_proposal(
        {
            "exception_id": exception.exception_id,
            "code": "",
            "hypothesis": "these two files cannot separate them",
            "evidence": list(exception.record_ids),
            "cannot_separate": list(exception.ambiguous_codes),
        },
        exceptions=index,
        taxonomy=taxonomy,
    )
    assert declined.ok, f"declining was refused: {declined.reasons}"


def test_the_derived_ambiguity_survives_the_decision_log(closed):
    """A field the writer sets and the reader never sees is this codebase's most
    repeated defect — `fingerprint` and `proof_id` both shipped that way. The
    checker above reads `ambiguous_codes` off a *replayed* exception, so if the
    log drops it, a guess becomes acceptable on the second read."""
    view, _labels, _runs = closed
    carried = [e.exception for e in view.exceptions if e.exception.ambiguous_codes]

    assert carried, (
        "no replayed exception carries its derived ambiguity, so the control that "
        "refuses a guess is reading an empty field"
    )
    for exception in carried:
        assert len(exception.ambiguous_codes) >= 2
        assert all(code in exception.hypothesis for code in exception.ambiguous_codes)


def test_a_transient_failure_is_retried_and_a_bad_request_is_not():
    """One rate limit used to lose an item. Three attempts now, on transient
    statuses only — retrying a 400 spends three times as long being wrong, and
    retrying a reply that was not a tool call would be ADR-001 dismantled by
    patience instead of by an `except` block."""
    from recon.triage import client

    assert client.RETRIES >= 2
    assert 429 in client.TRANSIENT_STATUS
    assert 500 in client.TRANSIENT_STATUS
    assert 400 not in client.TRANSIENT_STATUS
    assert 401 not in client.TRANSIENT_STATUS

    import inspect

    # Parsed, not grepped. Two earlier versions of this assertion failed on the
    # *comment inside the loop explaining why a refusal is not handled there* —
    # a substring check over source cannot tell code from the prose about it,
    # which is the same mistake as searching a module for the word "request".
    loop = ast.parse(textwrap.dedent(inspect.getsource(client.ModelEdge._post)))
    handled = {
        name
        for node in ast.walk(loop)
        if isinstance(node, ast.ExceptHandler | ast.Raise)
        for name in (n.id for n in ast.walk(node) if isinstance(n, ast.Name))
    }
    assert "ProposalRefused" not in handled, (
        "a refusal is raised or caught inside the retry loop, so the edge would "
        "retry until the model complies — ADR-001 dismantled by patience rather "
        "than by an except block"
    )

    body = inspect.getsource(client.ModelEdge._post)
    assert "for attempt in range(RETRIES)" in body, "there is no retry loop to speak of"
    assert "TRANSIENT_STATUS" in body, "the loop retries every status, including a 400"


def test_a_two_sided_break_is_one_item(closed):
    """One error, one row on the worklist.

    A wrong section leaves *both* rows unmatched, so raising one exception per
    unmatched row reported twenty items over eleven breaks — the same error
    twice, at the same amount, with the two record ids swapped. A controller
    works each twice, or notices and stops trusting the count, which is the
    number they plan a week from.

    The rule is mutual and agreeing: X's closest counterpart is Y, Y's closest
    is X, and both readings name the same code. One-directional closeness is not
    enough — three rows can each be closest to the same fourth, and folding
    unrelated breaks together is a worse error than counting one twice.
    """
    view, labels, _runs = closed

    derived = [e.exception for e in view.exceptions if e.exception.code != "E14"]
    two_sided = [e for e in derived if len(e.record_ids) == 2]

    # Section, quarter and rate errors leave a row on each side. Unbooked
    # deductions are genuinely one-sided and must *not* be paired with anything.
    expected_pairs = sum(
        labels["by_code"].get(code, 0)
        for code in ("X-TDS-SECTION-MISMATCH", "X-TDS-QUARTER-ERROR", "X-TDS-RATE-DIFF")
    )
    assert len(two_sided) == expected_pairs, (
        f"{len(two_sided)} paired breaks against {expected_pairs} planted two-sided ones"
    )

    for exception in two_sided:
        sides = {rid.split(":")[0] for rid in exception.record_ids}
        assert len(sides) == 2, (
            f"{exception.exception_id} pairs two rows from the same file: {exception.record_ids}"
        )

    unbooked = [e for e in derived if e.code == "X-TDS-UNBOOKED"]
    assert unbooked and all(len(e.record_ids) == 1 for e in unbooked), (
        "a one-sided break was paired with something"
    )


def test_pairing_loses_no_record(closed, batch):
    """Invariant 8 does not get to bend for a presentation fix.

    Merging two exceptions into one is exactly the shape of change that drops an
    input: the second row is no longer its own item, so if it is not carried in
    the surviving one it has silently left the close.
    """
    _summary, _labels, runs = closed
    source = looplib.get(LOOP).load(batch)
    every = {rec.record_id for _, rec in [*source.anchor_rows, *source.group_rows]}

    # Full detail, because the default view is a projection: it omits proofs and
    # group ids to keep a payload bounded, so every matched group row reads as
    # undisposed. Asserting invariant 8 off a summary would have failed for the
    # projection rather than for a lost record.
    run_id = _summary.run_id
    view = service.view(run_id, runs, detail=service.Detail.FULL)

    in_tail = {rid for e in view.exceptions for rid in e.exception.record_ids}
    in_matches = {m.anchor_id for m in view.matches}
    for match in view.matches:
        in_matches.update(match.group_ids or [])

    missing = every - in_tail - in_matches - set(view.out_of_scope)
    assert not missing, f"{len(missing)} record(s) have no disposition: {sorted(missing)[:4]}"
    assert view.ok


def test_a_paired_break_reports_the_larger_side_and_names_the_difference(closed):
    """A rate error has two amounts and the item needs one.

    The larger: a wrong section or quarter puts the whole deduction at risk of
    being disallowed, and a wrong rate puts the amount we *claimed* at risk of
    being restated. Ranking by the delta instead would put a rate error of a few
    rupees below a filing error worth hundreds, when the filing error is the one
    that can be disallowed entirely. The delta is stated in the evidence rather
    than hidden.
    """
    view, _labels, _runs = closed
    rate_errors = [
        e.exception
        for e in view.exceptions
        if e.exception.code == "X-TDS-RATE-DIFF" and len(e.exception.record_ids) == 2
    ]
    assert rate_errors, "no paired rate error in this batch"

    for exception in rate_errors:
        assert any("sides differ by" in line for line in exception.evidence), (
            f"{exception.exception_id} pairs two different amounts and does not say so"
        )
