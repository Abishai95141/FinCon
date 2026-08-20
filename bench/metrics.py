"""Scoring against ground truth.

Every rate ships with its decomposition. A headline match rate on its own is
gameable — matching everything maximises it — so `Scorecard.render` always
prints the false-match rate beside it, and `false_match_rate` is the number to
read first: an unmatched item costs a human a look, a wrongly matched one
corrupts the books.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from recon.contracts import Record

from .arms import ArmResult, Pairs


@dataclass(frozen=True)
class Scorecard:
    arm: str
    true_pairs: int
    produced: int
    correct: int
    false_matches: int
    missed: int
    notes: list[str]

    @property
    def auto_match_rate(self) -> float:
        return self.produced / self.true_pairs if self.true_pairs else 0.0

    @property
    def false_match_rate(self) -> float:
        """Of the matches produced, the share that are wrong. The metric that
        matters: a wrong match is far worse than an unmatched item."""
        return self.false_matches / self.produced if self.produced else 0.0

    @property
    def precision(self) -> float:
        return self.correct / self.produced if self.produced else 0.0

    @property
    def recall(self) -> float:
        return self.correct / self.true_pairs if self.true_pairs else 0.0

    @staticmethod
    def header() -> str:
        return (
            f"{'arm':<16} {'auto-match':>11} {'false-match':>12} "
            f"{'precision':>10} {'recall':>8} {'correct':>8} {'false':>6} {'missed':>7}"
        )

    def render(self) -> str:
        return (
            f"{self.arm:<16} {self.auto_match_rate:>10.1%} {self.false_match_rate:>11.2%} "
            f"{self.precision:>9.1%} {self.recall:>7.1%} "
            f"{self.correct:>8} {self.false_matches:>6} {self.missed:>7}"
        )


def external_index(records: list[tuple[str, Record]]) -> dict[str, Record]:
    return {ext: rec for ext, rec in records}


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


def score(result: ArmResult, truth: Pairs) -> Scorecard:
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
        notes=list(result.notes),
    )


def render_table(cards: list[Scorecard]) -> str:
    lines = [Scorecard.header(), "-" * len(Scorecard.header())]
    lines += [card.render() for card in cards]
    for card in cards:
        for note in card.notes:
            lines.append(f"  {card.arm}: {note}")
    return "\n".join(lines)
