"""Scoring against ground truth.

Every rate ships with its decomposition. A headline match rate on its own is
gameable — matching everything maximises it — so a rate here is not a float. It
is a `Rate`, and printing one prints `90.9% (20/22)` whether the caller
remembered the decomposition or not. `false_match_rate` is still the number to
read first: an unmatched item costs a human a look, a wrongly matched one
corrupts the books.

Two refusals are structural rather than advisory.

**An arm that did not run has no numbers.** `llm_only` is not built. A row of
`0.0%` would say we ran a model and it scored nothing, which is a claim about a
model we never called. Asking an absent arm for a rate raises.

**A match no tier produced is a match with no provenance.** The tier split must
account for every match the arm reports, or the scorecard refuses to exist.
That is invariant 2 in scorecard form: a match without a passing proof does not
appear in the match count, and the tiers are how the count is decomposed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .arms import ArmResult, Pairs
from .planted import ExceptionScore
from .rate import ArmAbsent, Rate

#: The eight metrics the plan claims, in the order they are rendered. Named so
#: a reader can tick them off against the page instead of taking the count on
#: trust — `EIGHT_METRICS` is asserted to appear in the output.
EIGHT_METRICS = (
    "auto-match",
    "precision",
    "recall",
    "false-match",
    "blocking recall",
    "exception coverage",
    "exception classification",
    "ambiguity detection",
)


@dataclass(frozen=True)
class Scorecard:
    arm: str
    absent: str | None = None
    """Why this arm produced no numbers. Set means the arm did not run."""

    true_pairs: int = 0
    produced: int = 0
    correct: int = 0
    false_matches: int = 0
    missed: int = 0

    tiers: dict[str, int] | None = None
    """How the matches were found. Required of any arm that produced one."""

    exceptions: ExceptionScore | None = None
    elapsed_ns: int | None = None
    records_scored: int = 0

    model_spend_paise: int | None = None
    """`None` means *absent*, not free. Nothing in this phase calls a model, so
    the cost of calling one is unknown."""

    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.absent:
            if self.produced or self.correct or self.false_matches or self.true_pairs:
                raise ValueError(
                    f"{self.arm} is declared absent but carries results — an arm that "
                    "did not run cannot contribute numbers to a comparison"
                )
            return
        if self.produced and self.tiers is None:
            raise ValueError(
                f"{self.arm} reports {self.produced} match(es) and no tier split. A match "
                "no tier produced is a match with no provenance (invariant 2)."
            )
        if self.tiers is not None and sum(self.tiers.values()) != self.produced:
            raise ValueError(
                f"{self.arm}: tier split {self.tiers} sums to {sum(self.tiers.values())}, "
                f"but {self.produced} match(es) are reported"
            )

    def _guard(self) -> None:
        if self.absent:
            raise ArmAbsent(f"{self.arm}: {self.absent}")

    @property
    def auto_match_rate(self) -> Rate:
        """Metric 1 — the headline throughput number."""
        self._guard()
        return Rate(self.produced, self.true_pairs)

    @property
    def false_match_rate(self) -> Rate:
        """Metric 4, and the one to read first. Of the matches produced, the
        share that are wrong."""
        self._guard()
        return Rate(self.false_matches, self.produced)

    @property
    def precision(self) -> Rate:
        self._guard()
        return Rate(self.correct, self.produced)

    @property
    def recall(self) -> Rate:
        self._guard()
        return Rate(self.correct, self.true_pairs)

    @property
    def records_per_second(self) -> int:
        self._guard()
        if not self.elapsed_ns:
            return 0
        return self.records_scored * 1_000_000_000 // self.elapsed_ns

    def elapsed_ms(self) -> int:
        return (self.elapsed_ns or 0) // 1_000_000

    def cost_line(self) -> str:
        """Metric 8's other half. `absent`, never `₹0.00` — see the module
        docstring on the absent arm."""
        if self.model_spend_paise is None:
            return "model spend absent (no model call in this arm)"
        return f"model spend ₹{self.model_spend_paise / 100:.2f}"

    def headline(self) -> str:
        """The one-line summary, with the decomposition attached by
        construction. There is no way to ask this object for the match rate on
        its own and get a sentence back."""
        self._guard()
        tiers = " ".join(f"{k}={v}" for k, v in sorted((self.tiers or {}).items())) or "none"
        return (
            f"{self.arm}: auto-match {self.auto_match_rate}  "
            f"false-match {self.false_match_rate}  tiers {tiers}"
        )

    @staticmethod
    def header() -> str:
        return (
            f"{'arm':<16} {'auto-match':>11} {'false-match':>12} "
            f"{'precision':>10} {'recall':>8} {'correct':>8} {'false':>6} {'missed':>7}"
        )

    def render(self) -> str:
        if self.absent:
            return f"{self.arm:<16} {'absent — ' + self.absent}"
        return (
            f"{self.arm:<16} {self.auto_match_rate.value:>10.1%} "
            f"{self.false_match_rate.value:>11.2%} "
            f"{self.precision.value:>9.1%} {self.recall.value:>7.1%} "
            f"{self.correct:>8} {self.false_matches:>6} {self.missed:>7}"
        )

    @staticmethod
    def exception_header() -> str:
        return (
            f"{'arm':<16} {'raised':>7} {'exception coverage':>20} "
            f"{'exception classification':>26} {'ambiguity detection':>21} "
            f"{'close':>9} {'rec/s':>8}"
        )

    def render_exceptions(self) -> str:
        if self.absent:
            return f"{self.arm:<16} {'absent — ' + self.absent}"
        score = self.exceptions
        if score is None:
            return f"{self.arm:<16} {'exception list not scored':>7}"
        return (
            f"{self.arm:<16} {score.raised:>7} {score.coverage!s:>20} "
            f"{score.classification!s:>26} {score.ambiguity!s:>21} "
            f"{self.elapsed_ms():>6} ms {self.records_per_second:>8}"
        )


def truth_pairs(labels_path: Path) -> Pairs:
    """Ground truth in external-id space: bank line -> the rows behind it.

    Payouts with no bank line in this period (the E01 timing case) have no true
    pair and are excluded from the denominator — counting them would penalise an
    arm for not matching something that is not there.
    """
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    pairs: Pairs = {}
    for entry in labels["payout_membership"].values():
        line = entry["bank_line"]
        if not line:
            continue
        pairs[line] = frozenset(entry["charges"] + entry["refunds"] + entry["fees"])
    return pairs


def truth_groups(labels_path: Path) -> dict[str, str]:
    """Ground truth as anchor external id -> the group_ref that truly backs it.

    Blocking recall needs the group, not the row set: a block proposes a
    (anchor, group) pair, so that is the unit its recall must be measured in.
    """
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    return {
        entry["bank_line"]: payout
        for payout, entry in labels["payout_membership"].items()
        if entry["bank_line"]
    }


def score(
    result: ArmResult,
    truth: Pairs,
    *,
    exceptions: ExceptionScore | None = None,
    elapsed_ns: int | None = None,
    records_scored: int = 0,
) -> Scorecard:
    if result.absent:
        return Scorecard(arm=result.name, absent=result.absent, notes=list(result.notes))

    correct = false = 0
    for anchor, claimed in result.pairs.items():
        if anchor in truth and truth[anchor] == claimed:
            correct += 1
        else:
            false += 1
    return Scorecard(
        arm=result.name,
        true_pairs=len(truth),
        produced=len(result.pairs),
        correct=correct,
        false_matches=false,
        missed=len(truth) - correct,
        tiers=dict(result.tiers),
        exceptions=exceptions,
        elapsed_ns=elapsed_ns,
        records_scored=records_scored,
        notes=list(result.notes),
    )


def render_table(cards: list[Scorecard]) -> str:
    """Two tables, because the second is the one that carries the argument.

    The first is match quality, where the fair baseline ties us. The second is
    the exception list, where it does not — and until this phase nothing
    measured it.
    """
    lines = [Scorecard.header(), "-" * len(Scorecard.header())]
    lines += [card.render() for card in cards]
    lines += ["", Scorecard.exception_header(), "-" * len(Scorecard.exception_header())]
    lines += [card.render_exceptions() for card in cards]
    lines.append("")
    for card in cards:
        for note in card.notes:
            lines.append(f"  {card.arm}: {note}")
    return "\n".join(lines)
