"""Which strategies a loop runs, and in what order — declared, not hardcoded.

`tiers.run` ran `T0, T1` in a literal tuple, then subset-sum, then the
disposition pass. The order was correct and invisible: nothing outside that
function could see it, change it, or add to it, so "the engine is
domain-agnostic" (invariant 7) held for *field names* and not for *behaviour*. A
loop that needed a fourth way of matching needed an engine edit, which is the
thing P15 exists to stop.

A profile now names its strategies in order and this module resolves them
against a closed registry. An unknown name is a profile error, never an
execution — the same rule the parse verbs live under (ADR-001), for the same
reason: a name that arrives from configuration must not be able to reach code
nobody wrote down.

**What a strategy may and may not do.** It proposes: given an anchor and the
groups still available, it either returns one group with the tier it claims, or
nothing. It does not verify — `close.match_and_verify` checks every proposal
against the records afterwards, and a strategy that could also verify itself
would be marking its own homework. It does not post, and it does not raise
exceptions; what is left over is the disposition pass's business.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from ..contracts import MatchTier, Record


@dataclass(frozen=True)
class Offer:
    """One anchor, the groups it may still be matched against, and the budget.

    `available` excludes groups an earlier strategy already claimed — a group
    backs exactly one anchor, and letting a later strategy re-offer a claimed
    group is how a match count starts exceeding the number of payouts.
    """

    anchor: Record
    available: Mapping[str, list[Record]]
    allowed: set[str] | None
    """Group refs blocking left in play, or None when blocking was exhaustive.
    A strategy that reaches outside this is reporting a recall number about
    itself rather than about the system."""

    profile: object
    residual: Callable[[Record, Sequence[Record]], Decimal]


@dataclass(frozen=True)
class Proposal:
    group_ref: str
    tier: MatchTier
    declared: Decimal | None = None
    """A residual this strategy states rather than absorbs.

    `None` means the proposal must close inside the profile's tolerance, which
    is every strategy but one. A partial payment is the exception: the money
    that arrived is real and the remainder is really unpaid, so absorbing the
    difference into tolerance would launder a loss, and refusing the match
    throws away a group the reference already identified.

    Whatever is declared here has to become an open item and stay in the
    unreconciled total (invariant 1) — the ledger's balance assertion is what
    makes that true rather than this field."""

    code: str | None = None
    """The exception a declared residual raises. A gap with no code would be a
    number in a proof that nobody has to work."""


#: A strategy: an offer in, at most one proposal out.
Strategy = Callable[[Offer], Proposal | None]


def _exact(offer: Offer) -> Proposal | None:
    """`T0` — the anchor names its group outright.

    Proposes; it does not decide what the proposal cost. The driver holds the
    tolerance budget and refuses a `T0` whose residual is not zero, and this
    checked the same thing again until the mutation suite pointed out that
    deleting the check here changed nothing. Two places computing one fact is
    how the copy nobody reads starts to rot.
    """
    ref = offer.anchor.source_row_id or ""
    if ref not in offer.available:
        return None
    if offer.allowed is not None and ref not in offer.allowed:
        return None
    return Proposal(ref, MatchTier.T0_EXACT)


def viable(offer: Offer) -> list[str]:
    """Every group that could back this anchor within the stated tolerance.

    Returns all of them, including when there is more than one. The caller
    refuses on anything but a single candidate — reporting the ambiguity rather
    than resolving it arbitrarily is the whole `E09` argument, and a function
    that returned only the first would make that impossible to notice.
    """
    profile = offer.profile
    want = offer.anchor.keys.get(profile.counterparty_key)
    found: list[str] = []
    for group_ref, group in sorted(offer.available.items()):
        if offer.allowed is not None and group_ref not in offer.allowed:
            continue
        if want is not None and {r.keys.get(profile.counterparty_key) for r in group} != {want}:
            continue
        if not any(
            profile.tolerance.within_window(offer.anchor.posted_on, r.posted_on) for r in group
        ):
            continue
        if abs(offer.residual(offer.anchor, group)) <= profile.tolerance.absolute:
            found.append(group_ref)
    return found


def _tolerant(offer: Offer) -> Proposal | None:
    """`T1` — *one* group closes within the profile's stated tolerance.

    Two viable groups is an ambiguity, and picking either produces a confident
    wrong answer, so this returns nothing and the anchor falls through to
    whatever the profile declared next.
    """
    found = viable(offer)
    return Proposal(found[0], MatchTier.T1_TOLERANT) if len(found) == 1 else None


def _partial_payment(offer: Offer) -> Proposal | None:
    """`E04` — the reference is unambiguous and the money is short.

    Deliberately narrow. It fires only when the anchor names its group outright,
    which is what keeps a declared residual from becoming a way to match
    anything to anything: this is not free matching with the difference waved
    through, it is "we know which payout this is and we know exactly how much
    never arrived".

    An overpayment is `E05` and a different conversation — a credit balance is
    not a receivable — so only shortfalls are proposed here.
    """
    ref = offer.anchor.source_row_id or ""
    if ref not in offer.available:
        return None
    if offer.allowed is not None and ref not in offer.allowed:
        return None

    residual = offer.residual(offer.anchor, offer.available[ref])
    if abs(residual) <= offer.profile.tolerance.absolute:
        return None  # `exact` or `tolerant` owns this; a shortfall it is not
    if residual >= 0:
        return None  # not short — an overpayment is E05

    # A shortfall that a repeated row already accounts for is not a partial
    # payment. Found by running it: on the first pass this claimed the
    # duplicated-export payout, because a group carrying a row twice sums to
    # more than the credit and looks exactly like short payment. Booking that as
    # `E04` puts a receivable on a counterparty who owes nothing — the money was
    # never short, the export was wrong.
    #
    # `key_occurrence` is content-derived identity, so this asks a general
    # question — "is this row a repeat of another row in the same group?" — and
    # knows nothing about gateways or exports.
    shortfall = abs(residual)
    repeated = [r for r in offer.available[ref] if r.key_occurrence > 0]
    if repeated and abs(sum((r.amount for r in repeated), Decimal("0.00"))) == shortfall:
        return None

    return Proposal(ref, MatchTier.T4_DECLARED, declared=shortfall, code="E04")


#: The closed vocabulary. A profile naming anything else is refused before a
#: close begins, the way an adapter spec naming an unknown verb is.
STRATEGIES: dict[str, Strategy] = {
    "exact": _exact,
    "tolerant": _tolerant,
    "partial_payment": _partial_payment,
}

#: Strategies that operate over a pool rather than one anchor at a time, and so
#: run as a pass of their own after the per-anchor ones. Named here so a profile
#: can order them alongside the rest and a reader can see the whole sequence in
#: one place.
POOL_STRATEGIES = frozenset({"subset_sum"})


class StrategyError(ValueError):
    """A profile named a strategy that does not exist. A configuration error,
    never an attempt — see ADR-001."""


def resolve(names: Sequence[str]) -> list[str]:
    """Check a declared sequence before a close runs on it.

    Eagerly, and before any matching: a profile with a typo in its fourth
    strategy should fail at the top rather than three tiers into a close, with
    half a ledger written.
    """
    unknown = [n for n in names if n not in STRATEGIES and n not in POOL_STRATEGIES]
    if unknown:
        raise StrategyError(
            f"profile declares unknown strategy {unknown}; known: "
            f"{sorted(set(STRATEGIES) | POOL_STRATEGIES)}"
        )
    if not names:
        raise StrategyError("a profile that declares no strategies can never match anything")
    return list(names)
