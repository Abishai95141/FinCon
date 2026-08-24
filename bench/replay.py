"""Score a close from its decision log alone.

This is the P9 gate made executable: read the file, rebuild what was decided,
and run the *same* scorer over it that the live run used. Nothing here recomputes
a match, and nothing here reads a number the log carries — the terminator's
scorecard digest is compared against a scorecard this module derives, never
copied from.

Sharing `score()` and `score_planted()` with the live path is deliberate. A
replay with its own scorer would agree with the run only when both are right,
and would agree with itself when both are wrong the same way.
"""

from __future__ import annotations

from pathlib import Path

from recon.journal import read
from recon.journal.replay import ReplayedClose, disagreements, replay

from .arms import ArmResult
from .metrics import Scorecard, score, scorecard_digest, truth_pairs
from .planted import load_planted, score_planted

__all__ = ["disagreements", "replay_close", "scorecard_digest", "scorecard_from_log"]

IN_SCOPE_LEGS = {"bank"}


def replay_close(path: Path, *, verify: bool = True) -> ReplayedClose:
    return replay(read(path, verify=verify))


def scorecard_from_log(
    path: Path, labels_path: Path, *, verify: bool = True, arm: str = "deterministic"
) -> Scorecard:
    """Rebuild the arm's scorecard from the log and the labels.

    The labels are ground truth and were always an input to scoring — reading
    them here is not reading the answer. Everything about what the *system did*
    comes from the events.
    """
    replayed = replay_close(path, verify=verify)
    result = ArmResult(
        name=arm,
        pairs=replayed.pairs,
        tiers=replayed.tiers,
        exceptions=replayed.exceptions,
        notes=[f"replayed from {path}"],
    )
    planted = load_planted(labels_path, replayed.external_of)
    return score(
        result,
        truth_pairs(labels_path),
        exceptions=score_planted(planted, replayed.exceptions, in_scope_legs=IN_SCOPE_LEGS),
        elapsed_ns=None,
        records_scored=0,
    )
