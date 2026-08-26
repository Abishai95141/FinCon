"""Read a near miss and name the failure, or say why it cannot be named.

`nearmiss` says *which component* an unmatched row failed on. When exactly one
component differs and the loop has declared what that means, the diagnosis is
arithmetic: same deductor, same section, same amount, different quarter is a
timing error and nothing else. No model is needed and none should be used — a
proposal is `P2 ATTESTED` at best and this is derivable from the raw files, so
routing it through a model would take a `P0`-grade answer and downgrade it.

**The interesting half is what this refuses.** Two of the TDS codes —
"deducted but never deposited" and "deposited against the wrong PAN" — produce
*identical* evidence: a row in our ledger with nothing on the government's side.
That is not a gap in the generator; it is true of the real filing. Your own 26AS
cannot tell you whether the deductor failed to deposit or deposited the money
against somebody else's PAN, and you find out by asking them.

So this returns an **ambiguity** rather than a pick, exactly as `E09` does for
subset-sum. A classifier that chose between two indistinguishable causes would be
right about half the time and confident every time, and the wrong half routes a
correction return to a deductor who did nothing wrong.

**Domain-agnostic.** The mapping from "these parts differ" to "this is the code"
is profile data. This module knows only how to read a near miss, apply a
declared mapping, and refuse when the mapping is not decisive.
"""

from __future__ import annotations

from dataclasses import dataclass

from .nearmiss import NearMiss

#: Parts that, when they are the *only* difference, are decisive on their own.
#: Anything else — two or more differing parts, or a part the loop never declared
#: — is not diagnosed here.
DECISIVE_WIDTH = 1


@dataclass(frozen=True)
class Diagnosis:
    """What the evidence supports. Possibly more than one thing."""

    codes: tuple[str, ...]
    reason: str
    derived: bool
    """True when this came from the arithmetic rather than from a default.

    Load-bearing: a derived code is `P0`-grade and a model proposal may not
    overwrite it. `triage` reads this field to decide whether to even offer the
    item.
    """

    @property
    def decided(self) -> bool:
        return self.derived and len(self.codes) == 1

    @property
    def ambiguous(self) -> bool:
        return self.derived and len(self.codes) > 1

    @property
    def code(self) -> str:
        if not self.decided:
            raise ValueError(f"asked for the code of a diagnosis that is not decided: {self.codes}")
        return self.codes[0]


@dataclass(frozen=True)
class DiagnosisRules:
    """A loop's declared reading of its own near misses.

    Data, not code. `settlement_3way` declares none and diagnoses nothing, which
    is correct: a payout reference has no parts to differ on, so there is nothing
    for this to read.
    """

    #: frozenset of differing part names -> the code that means
    by_difference: dict[frozenset[str], str]

    #: side name -> the codes that are possible when a row on that side has no
    #: counterpart at all. A tuple, because more than one is the honest answer
    #: when the files cannot separate them.
    by_absence: dict[str, tuple[str, ...]]

    #: Why the absence set is ambiguous, in one sentence, for the record and for
    #: the person reading the worklist. Required when any absence set has more
    #: than one code — an ambiguity with no explanation is a shrug.
    absence_reason: str = ""

    def __post_init__(self) -> None:
        if any(len(codes) > 1 for codes in self.by_absence.values()) and not self.absence_reason:
            raise ValueError(
                "an absence maps to more than one code and no reason is given; "
                "an ambiguity nobody explained is indistinguishable from a bug"
            )


def _absence(miss: NearMiss, rules: DiagnosisRules) -> Diagnosis:
    """This row has no counterpart. What that means, per side."""
    codes = rules.by_absence.get(miss.side, ())
    if not codes:
        return Diagnosis(
            codes=(),
            reason=(
                f"nothing within one component of {miss.record_id}, and this loop has "
                f"not declared what an absent counterpart on the {miss.side!r} side means"
            ),
            derived=False,
        )
    tail = f" {rules.absence_reason}" if len(codes) > 1 else ""
    return Diagnosis(
        codes=codes,
        reason=(
            f"{miss.considered} row(s) compared and none is within one key component "
            f"of {miss.record_id}, so it has no counterpart on the other side.{tail}"
        ),
        derived=True,
    )


def diagnose(miss: NearMiss, rules: DiagnosisRules) -> Diagnosis:
    """Name the failure this near miss describes, or decline.

    **Absence is "nothing is one component away", not "nothing resembles it".**
    The first version tested for zero candidates and that branch was unreachable:
    with a key of party+section+quarter, some other row always shares the party,
    so a genuinely-absent counterpart still produced four near misses and fell
    through to "not derived". Two `X-TDS-UNBOOKED` rows sat as `E14` while the
    rule that named them was right there.

    A row is a counterpart when it is one component away. If none is, this row
    has no counterpart, whatever else happens to be in the file.
    """
    if not miss.candidates:
        return _absence(miss, rules)

    closest = miss.candidates[0]
    if len(closest.differs_on) != DECISIVE_WIDTH:
        return _absence(miss, rules)

    code = rules.by_difference.get(frozenset(closest.differs_on))
    if code is None:
        return Diagnosis(
            codes=(),
            reason=(
                f"the closest row differs only on {closest.differs_on[0]!r} and this "
                f"loop has not declared what that means"
            ),
            derived=False,
        )

    # A second candidate that is *equally* close and reads differently is an
    # ambiguity, not a diagnosis — the same argument E09 makes about two subsets
    # that both sum correctly.
    rivals = [
        c
        for c in miss.candidates[1:]
        if c.strength == closest.strength
        and len(c.differs_on) == DECISIVE_WIDTH
        and rules.by_difference.get(frozenset(c.differs_on)) not in (None, code)
    ]
    if rivals:
        others = sorted({rules.by_difference[frozenset(c.differs_on)] for c in rivals} | {code})
        return Diagnosis(
            codes=tuple(others),
            reason=(
                f"{len(rivals) + 1} rows are equally close to {miss.record_id} and they "
                f"do not agree on what went wrong"
            ),
            derived=True,
        )

    detail = closest.detail[closest.differs_on[0]]
    return Diagnosis(
        codes=(code,),
        reason=(
            f"{miss.record_id} and {closest.record_id} agree on "
            f"{'+'.join(closest.agrees_on)} and differ only on "
            f"{closest.differs_on[0]} ({detail})"
        ),
        derived=True,
    )
