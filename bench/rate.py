"""A rate that cannot be printed without its decomposition.

CLAUDE.md rule 1 bans "reporting match rate without false-match rate and tier
split" because a headline number alone is gameable. A bare `float` makes
omitting the decomposition the path of least resistance: `print(f"{rate:.1%}")`
is shorter than the honest version and looks the same in review. So rates are
not floats here. `str(Rate(20, 22))` is `90.9% (20/22)`, and the lazy call site
produces the honest output.

`ArmAbsent` lives here for the same reason. An arm that did not run has no
number, and the wrong answer to "what did it score" is zero.
"""

from __future__ import annotations

from dataclasses import dataclass


class ArmAbsent(Exception):
    """A number was asked of an arm that did not run.

    Raised rather than returning zero. A zero propagates into a comparison and
    reads as a measurement; this stops at the caller.
    """


@dataclass(frozen=True)
class Rate:
    numerator: int
    denominator: int

    @property
    def value(self) -> float:
        return self.numerator / self.denominator if self.denominator else 0.0

    @property
    def defined(self) -> bool:
        """A rate over an empty denominator is not zero — there was nothing to
        be right or wrong about."""
        return self.denominator > 0

    def __str__(self) -> str:
        if not self.defined:
            return "n/a (0/0)"
        return f"{self.value:.1%} ({self.numerator}/{self.denominator})"

    def __format__(self, spec: str) -> str:
        return format(str(self), spec)
