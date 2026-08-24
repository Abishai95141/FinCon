"""Known-broken items, as reproducers that fail on purpose.

STATUS.md carried a hand-maintained table of open problems and roughly a quarter
of its rows were wrong: `F1`-`F4` sat there marked **CRITICAL** for four phases
after being closed at P7/P8, and "No control plane" stayed open while three
modules enforced one. Nobody was lying  -  writing the row felt like discharging
the obligation, and nothing ever asked again.

So the table stops being written by hand. Each machine-checkable problem is an
`xfail(strict=True)` reproducer here. `strict` is what gives it teeth: an
**XPASS** fails the suite, so the day a problem is fixed CI breaks and the row
has to be removed. A fix can no longer land unnoticed.

**What this does not cover, stated rather than implied.** Only problems with a
minimal reproducer live here. Rows like "everything is validated at toy scale"
or "every audit is one person auditing their own design" are true, important and
not expressible as a failing assertion; they stay prose in STATUS and stay
un-policed. The mechanism covers what it can, and `make status-table` prints
which is which.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.known_broken


def test_no_domain_constants_in_kernel_code():
    """Invariant 7, enforced instead of documented.

    Widened past the instance that prompted it. `Assets:Bank:HDFC` was the
    obvious leak; a default of `currency = "INR"` was the same class and nothing
    was looking for it — a source that declared no currency was read as rupees,
    which is not a missing field but a wrong number nothing downstream can
    contradict.

    So the check is for domain *constants*, not for one chart: account names,
    currency codes and counterparty names anywhere under `src/recon`. It catches
    the next one too, which is the only reason it is worth having.
    """
    account = re.compile(r"^(Assets|Liabilities|Equity|Income|Expenses):")
    iso4217 = re.compile(r"^(INR|USD|EUR|GBP|AED|SGD|JPY)$")
    counterparty = re.compile(r"^(razorpay|cashfree|stripe|adyen|payu)$", re.IGNORECASE)

    offenders: list[str] = []
    for path in sorted(Path("src/recon").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            value = node.value
            if account.match(value) or iso4217.match(value) or counterparty.match(value):
                offenders.append(f"{path}:{node.lineno} {value!r}")
    assert not offenders, (
        "domain constants in the engine belong in a profile or an adapter spec "
        f"(invariant 7): {offenders}"
    )


# Was xfail(strict) from P8 until 2026-08-25: no model-induced rule had ever
# been promoted, so nothing attributed improvement rule by rule. `R-DUP-06`
# does — deepseek-v4-flash, from a controller's own words, `raise_advisory ->
# E06` on a repeated export row. Exception classification 1/5 -> 2/5 on batch A
# *and* on held-out B, no false match, no value moved.
#
# It took two refusals to get here, both of them the system working: the first
# rule removed ₹5,489.75 and destroyed the finding it was meant to raise, and
# the second named no code and re-coded nothing. The row is green because the
# gate refused twice, not because it stopped asking.
def test_a_model_induced_rule_has_been_promoted():
    from pathlib import Path as _P

    from recon.contracts.rule import Rule, RuleStatus

    stored = list(_P("data/rules").glob("*.json"))
    assert stored, "no promoted rule is stored, so no close can be attributed to one"
    for path in stored:
        for entry in __import__("json").loads(path.read_text())["promoted"]:
            rule = Rule(**entry)
            assert rule.status is RuleStatus.PROMOTED
            assert rule.promotion is not None, "a promoted rule with no promotion event"
            assert rule.promotion.promoted_by, "promotion with no named actor"


@pytest.mark.xfail(
    strict=True,
    reason="Policy and taxonomy are pinned by digest but not signed. The digest "
    "proves what ran, not who approved it.",
)
def test_policy_carries_a_signature():
    from bench.run import SETTLEMENT_POLICY

    assert hasattr(SETTLEMENT_POLICY, "signature")
