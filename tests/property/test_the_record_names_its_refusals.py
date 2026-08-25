"""Two decisions a close made and never wrote down.

Found by building a surface that serves *only* what the record says. Both are
refusals, which is the pattern: `derive` was built to walk the structures the
completeness audit walks, and these two never entered those structures, so a log
written by set arithmetic over them still missed both.

**A rule that broke a match.** Invariant 5 — "a rule cannot be promoted if it
breaks a historical match" — is not advisory, and `run_close` computes the
breakage on every close with a bundle. It set `ok=False` and reached the log
nowhere at all: the one artifact an auditor is handed said nothing about the one
thing that had gone wrong.

**A rule refused as inadmissible.** An approval granted under a policy that is
no longer in force is not an approval, and the close correctly declines to apply
such a rule. It then said nothing, so a rule sitting in the store doing nothing
looked identical to a rule doing its job.

Neither fires on batches A or B, which is exactly why they went eleven and one
phases respectively without being noticed — a refusal that never happens on the
corpus is invisible to every test that runs the corpus. So each is constructed
here.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from recon import loop as looplib
from recon import service
from recon.close import CloseRequest, run_close
from recon.contracts.rule import ActionKind, Predicate, Rule, RuleAction
from recon.engine import rulestore
from tests.conftest import promoted

LOOP = "settlement_3way"
BATCH = "A"


def _request(tmp_path: Path, rules: list[Rule]) -> CloseRequest:
    lp = looplib.get(LOOP)
    sources = lp.load(Path("data/batches") / BATCH)
    return CloseRequest(
        run_id="constructed",
        anchors=sources.anchor_rows,
        groups=sources.group_rows,
        profile=lp.profile,
        policy=lp.policy(),
        taxonomy=lp.taxonomy(),
        chart=lp.chart(),
        period=lp.period,
        opened_on=lp.opened_on,
        journal_path=tmp_path / "decisions.jsonl",
        source_proofs=sources.proofs,
        provenance=sources.provenance,
        out_of_scope=sources.scope,
        rules=rules,
    )


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def a_rule_that_breaks_a_match(tmp_path: Path) -> Rule:
    """Suppress a row out of a group that currently matches.

    Aimed by content, not by id: the rule fires on the counterparty of a group
    the close matched, so removing its rows leaves the anchor unable to close.
    Keying on record ids would be refused structurally — and would also be the
    kind of rule a firing count cannot police.
    """
    baseline = run_close(_request(tmp_path / "baseline", []))
    match = next(m for m in baseline.matches if len(m.group_ids) > 1)
    victim = baseline.records[match.group_ids[0]]
    return promoted(
        Rule(
            rule_id="R-BREAKER",
            version=1,
            profile=LOOP,
            when=[
                Predicate(field="keys.gateway", op="eq", value=victim.keys["gateway"]),
                Predicate(field="keys.row_type", op="eq", value=victim.keys["row_type"]),
            ],
            then=[RuleAction(kind=ActionKind.SUPPRESS, reason="constructed to break a match")],
        )
    )


def test_a_rule_that_breaks_a_match_is_named_in_the_record(
    tmp_path: Path, a_rule_that_breaks_a_match: Rule
):
    outcome = run_close(_request(tmp_path / "ruled", [a_rule_that_breaks_a_match]))

    assert outcome.matches_broken_by_rules, (
        "the constructed rule broke nothing — the fixture has stopped exercising "
        "invariant 5 and this test is measuring an empty set"
    )
    assert not outcome.ok

    blocked = [e for e in _events(outcome.journal_path) if e["kind"] == "CloseBlocked"]
    assert blocked, "a rule broke a match and the decision log said nothing"
    reasons = [r for e in blocked for r in e["payload"]["reasons"]]
    joined = " ".join(reasons)
    assert "rule_broke_match" in joined
    for anchor in outcome.matches_broken_by_rules:
        assert anchor in joined, f"{anchor} was broken and is not named in the record"

    # The close is stuck for *two* separate reasons now — the rule broke a match
    # and there are items waiting on a human — and the record has to carry both.
    # `derive` used to write `blocked_reasons or [sign-off line]`, so a hard
    # blocker deleted the sign-off queue from the log entirely, and the p19
    # mutation reverting that survived: every other test here runs a close with
    # no hard blocker, where `or` and `+` are indistinguishable. This is the only
    # state that tells them apart.
    assert any("sign-off" in r for r in reasons), (
        "a hard blocker erased the sign-off queue from the record — two different "
        "problems for two different people, collapsed into one"
    )
    assert blocked[0]["payload"]["blocking_exceptions"]


def test_the_surface_shows_a_broken_match_rather_than_a_clean_close(
    tmp_path: Path, a_rule_that_breaks_a_match: Rule
):
    """The reason this was found at all: a page served from the record would
    have rendered a close that lost a match as a close that went fine."""
    runs = tmp_path / "runs"
    request = dataclasses.replace(
        _request(tmp_path, [a_rule_that_breaks_a_match]),
        journal_path=runs / "shown" / "decisions.jsonl",
    )
    outcome = run_close(request)
    view = service.view("shown", runs)
    assert not view.ok
    assert any("rule_broke_match" in reason for reason in view.blocked), view.blocked
    assert outcome.matches_broken_by_rules


def test_a_rule_refused_as_inadmissible_is_named_in_the_record(tmp_path: Path):
    """An approval granted under a policy no longer in force is not an approval.

    The close already declined to apply it. What it did not do was say so, and a
    refusal nobody records reads exactly like a rule that worked.
    """
    shipped = rulestore.load(LOOP)
    assert shipped, (
        "no promoted rule to re-approve under the wrong policy — R-DUP-06 ships, "
        "so an empty store means the rule store stopped loading"
    )
    stale = promoted(shipped[0], actor="someone", policy_ref="some-other-policy@v99")

    outcome = run_close(_request(tmp_path / "stale", [stale]))
    assert stale.rule_id in outcome.inadmissible

    refused = [e for e in _events(outcome.journal_path) if e["kind"] == "ProposalRefused"]
    assert refused, "an inadmissible rule was declined and the record did not mention it"
    payload = refused[0]["payload"]
    assert payload["subject"] == stale.rule_id
    assert payload["proposal_kind"] == "promoted_rule"
    assert any("some-other-policy@v99" in r for r in payload["reasons"]), payload["reasons"]


def test_the_two_states_a_close_can_be_stuck_in_stay_apart(tmp_path: Path):
    """ "The books do not balance" and "five items need a human" are different
    problems for different people.

    `derive` used to collapse them: a ledger error replaced the sign-off line
    entirely, so a close with both looked like a close with one. Constructed
    here because batches A and B only ever produce the second.
    """
    outcome = run_close(_request(tmp_path / "both", []))
    blocked = [e for e in _events(outcome.journal_path) if e["kind"] == "CloseBlocked"]
    assert blocked, "this batch raises blocking exceptions; the record should say so"
    payload = blocked[0]["payload"]
    assert payload["blocking_exceptions"], "the ids of the blocking items are not recorded"
    assert any("sign-off" in r for r in payload["reasons"])

    view = service.view(Path(outcome.journal_path).parent.name, tmp_path)
    assert view.blocking_exceptions, "the surface lost the sign-off queue"
    assert not view.blocked, (
        "items waiting on a human were reported as the books failing to balance"
    )
    assert view.ok, "a close with a normal exception queue was reported as a failed run"
