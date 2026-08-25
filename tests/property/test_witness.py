"""A proof must be a witness, not a receipt.

Certifying-algorithm framing: a checker accepts `(x, y, w)` iff `w` proves
`y = f(x)`. Until 7.0.0 the witness omitted what a rule removed from `x`, so
after a suppression the legs summed honestly to the anchor and the *claim* was
under-determined. Measured on 2026-08-25, all three of these verified:

    verify(genuine P1 proof)                 -> proven
    verify(rule_id -> "R-DOES-NOT-EXIST")    -> proven
    verify(tier relabelled P1 -> P0)         -> proven

The tier was enforced where the proof was built and nowhere it was checked.
"""

from __future__ import annotations

import pytest
from bench.run import SETTLEMENT_3WAY, SETTLEMENT_POLICY, close, load_sides

from recon.contracts import ProofTier
from recon.contracts.rule import ActionKind, Operator, Predicate, Rule, RuleAction, RuleStatus
from recon.engine import rulestore
from recon.engine.tiers import run as run_tiers
from recon.engine.verifier import verify

SUPPRESS = Rule(
    rule_id="R-WIT",
    profile="settlement_3way",
    when=[Predicate(field="key_occurrence", op=Operator.GT, value="0")],
    then=[RuleAction(kind=ActionKind.SUPPRESS, reason="a repeat of an asserted event")],
)


@pytest.fixture(scope="module")
def ruled():
    """A close whose duplicate group only balances because a rule removed rows."""
    sides = load_sides("A")
    run = run_tiers(
        [r for _, r in sides.anchors],
        [r for _, r in sides.settlement],
        SETTLEMENT_3WAY,
        ProofTier.P0_ARITHMETIC,
        policy=SETTLEMENT_POLICY,
        out_of_scope=sides.scope,
        rules=[SUPPRESS],
        simulate=True,
    )
    records = {r.record_id: r for _, r in sides.bank + sides.settlement}
    match = next(m for m in run.matches if m.proof.provenance is ProofTier.P1_RULE)
    return match.proof, records, sides.scope


def _verdict(proof, records, scope, bundle=(SUPPRESS,)):
    return verify(proof, records, SETTLEMENT_POLICY, bundle=bundle, declared_scope=scope)


def test_a_genuine_rule_assisted_proof_verifies(ruled):
    proof, records, scope = ruled
    assert _verdict(proof, records, scope).proven


def test_a_forged_rule_id_is_refused(ruled):
    proof, records, scope = ruled
    verdict = _verdict(proof.model_copy(update={"rule_id": "R-DOES-NOT-EXIST"}), records, scope)
    assert not verdict.proven
    assert any("not in the bundle" in r for r in verdict.reasons), verdict.reasons


def test_a_tier_laundered_to_arithmetic_is_refused(ruled):
    """The one that matters most. `P0 ARITHMETIC` says a third party re-deriving
    from raw records reaches this residual. After a suppression they do not."""
    proof, records, scope = ruled
    laundered = proof.model_copy(
        update={"provenance": ProofTier.P0_ARITHMETIC, "rule_id": None, "rule_version": None}
    )
    verdict = _verdict(laundered, records, scope)
    assert not verdict.proven
    assert any("absent from the legs" in r for r in verdict.reasons), verdict.reasons


def test_a_p1_proof_naming_no_rule_is_refused(ruled):
    proof, records, scope = ruled
    verdict = _verdict(proof.model_copy(update={"rule_id": None}), records, scope)
    assert not verdict.proven
    assert any("names no rule" in r for r in verdict.reasons), verdict.reasons


def test_a_proof_is_not_verifiable_without_the_bundle_it_cites(ruled):
    """The bundle is a separate input for the reason policy is: a proposer may
    not hand in the rules that excuse its own proof."""
    proof, records, scope = ruled
    assert not _verdict(proof, records, scope, bundle=()).proven


def test_a_rule_swapped_under_its_own_id_is_refused(ruled):
    """The attack a rule id alone cannot survive: same name, different predicate.
    The checker re-runs the rule rather than trusting that the id still means
    what it meant, so a bundle edited after the fact does not verify."""
    proof, records, scope = ruled
    swapped = SUPPRESS.model_copy(
        update={"when": [Predicate(field="side", op=Operator.EQ, value="settlement")]}
    )
    verdict = _verdict(proof, records, scope, bundle=(swapped,))
    assert not verdict.proven
    assert any("does not account for the partition" in r for r in verdict.reasons), verdict.reasons


def test_honest_arithmetic_proofs_are_untouched():
    """The regression that matters. A checker that refuses forgeries and also
    refuses honest work has not helped."""
    plain = close("A", rules=[])
    assert plain.matches
    for match in plain.matches:
        assert verify(
            match.proof, plain.records, SETTLEMENT_POLICY, declared_scope=plain.scope
        ).proven, match.match_id


def test_the_shipped_close_still_verifies_under_its_own_bundle():
    shipped = close("A")
    bundle = rulestore.load(SETTLEMENT_3WAY.name)
    assert shipped.matches
    for match in shipped.matches:
        assert verify(
            match.proof,
            shipped.records,
            SETTLEMENT_POLICY,
            bundle=bundle,
            declared_scope=shipped.scope,
        ).proven, match.match_id


def test_every_proof_names_the_bundle_that_was_active():
    """A decision that names the bundle which produced it is what lets a checker
    fetch the same rules a year later instead of taking a rule id on trust."""
    shipped = close("A")
    digest = rulestore.bundle_digest(rulestore.load(SETTLEMENT_3WAY.name))
    assert digest != "empty"
    for match in shipped.matches:
        assert match.proof.rule_bundle_digest == digest, match.match_id


def test_a_declared_out_of_scope_row_is_not_mistaken_for_a_rule_exclusion():
    """The false positive this clause could easily have. A row the *caller* put
    out of scope is a disposition the close made openly; it is part of the input
    a checker is given, not evidence that a rule quietly acted."""
    sides = load_sides("A")
    groups = [r for _, r in sides.settlement]
    victim = next(r for r in groups if r.group_ref)
    scope = {**sides.scope, victim.record_id: "declared out of scope by the caller"}
    run = run_tiers(
        [r for _, r in sides.anchors],
        groups,
        SETTLEMENT_3WAY,
        ProofTier.P0_ARITHMETIC,
        policy=SETTLEMENT_POLICY,
        out_of_scope=scope,
    )
    records = {r.record_id: r for _, r in sides.bank + sides.settlement}
    for match in run.matches:
        verdict = verify(match.proof, records, SETTLEMENT_POLICY, declared_scope=scope)
        assert verdict.proven, (match.match_id, verdict.reasons)


def test_a_promoted_rule_that_is_not_in_the_store_cannot_launder_a_close():
    """End to end: the close hands the verifier exactly the bundle it ran with,
    so a match made by a rule nobody promoted cannot survive its own close."""
    rogue = SUPPRESS.model_copy(update={"rule_id": "R-ROGUE", "status": RuleStatus.DRAFT})
    result = close("A", rules=[rogue])
    assert not any(m.proof.rule_id == "R-ROGUE" for m in result.matches)
