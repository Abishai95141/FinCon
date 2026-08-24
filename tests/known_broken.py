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
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.known_broken


@pytest.mark.xfail(
    strict=True,
    reason="#4 the regression is match-shaped: `book_to` changes where money posts, "
    "not which rows match, so a match-delta regression cannot measure it. It is "
    "refused rather than measured. Closing this needs a posting-delta regression.",
)
def test_book_to_is_measurable_by_the_regression():
    from recon.engine.promotion import MODELLED_ACTIONS

    assert "book_to" in MODELLED_ACTIONS


@pytest.mark.xfail(
    strict=True,
    reason="#4 (second half) `normalize_key` can add matches by making records "
    "comparable that were not. The regression does not simulate it.",
)
def test_normalize_key_is_measurable_by_the_regression():
    from recon.engine.promotion import MODELLED_ACTIONS

    assert "normalize_key" in MODELLED_ACTIONS


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


@pytest.mark.xfail(
    strict=True,
    reason="CLAUDE.md rule 6 promises end-to-end tests. `tests/e2e/` is empty and "
    "`make e2e` exits non-zero. The gates are the de-facto e2e suite, so the fix "
    "is probably to reconcile the wording, not to fill a directory.",
)
def test_make_e2e_succeeds():
    assert subprocess.run(["make", "e2e"], capture_output=True).returncode == 0


@pytest.mark.xfail(
    strict=True,
    reason="CLAUDE.md rule 6 promises unit tests on real inputs. `tests/unit/` is empty.",
)
def test_unit_tests_exist():
    assert list(Path("tests/unit").glob("test_*.py"))


@pytest.mark.xfail(
    strict=True,
    reason="P12: adapter-spec synthesis is the last third and is unbuilt, so the "
    "gate's 'an unseen format ingests with no configuration' half is unmet.",
)
def test_adapter_synthesis_has_a_producer():
    from recon.contracts import PRODUCERS, EventKind

    assert not PRODUCERS[EventKind.ADAPTER_AUTHORED].startswith("P")


@pytest.mark.xfail(
    strict=True,
    reason="P12: zero rules have been promoted end-to-end, so nothing attributes "
    "improvement rule by rule  -  which is the gate's own sentence. The dedup rule "
    "promotes when constructed by hand; the model has not yet written one that does.",
)
def test_a_model_induced_rule_has_been_promoted():
    from pathlib import Path as _P

    assert list(_P("data/rules").glob("*.json")) if _P("data/rules").exists() else False


@pytest.mark.xfail(
    strict=True,
    reason="Policy and taxonomy are pinned by digest but not signed. The digest "
    "proves what ran, not who approved it.",
)
def test_policy_carries_a_signature():
    from bench.run import SETTLEMENT_POLICY

    assert hasattr(SETTLEMENT_POLICY, "signature")
