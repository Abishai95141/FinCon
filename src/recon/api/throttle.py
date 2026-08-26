"""A bound on how fast one caller may ask a question.

Built for one specific trade. Splitting sign-in from create-account means the
signup form has to say "that address already has an account" — otherwise a
person who typos into the wrong tab is told it worked and then cannot sign in.
That sentence is an account-enumeration oracle: anyone can type addresses in and
learn which ones have FinCon accounts, which for a finance product is a phishing
list with the targets pre-qualified.

The leak is accepted deliberately (see `docs/12-AUTH.md`). What is not
acceptable is leaving it *fast*. One address at a time, from one address, at
this rate, is a person who made a mistake; ten thousand is a scrape.

**What this is not.** It is per-process and in-memory, so it resets on deploy and
does not add up across tasks. With one Fargate task that is the whole system;
with two it is half a bound, and the honest fix then is a shared store rather
than a larger number here. `state()` reports the truth so a surface can say so.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Limit:
    """A token bucket: `burst` requests at once, refilling to `per_window`."""

    per_window: int
    window_seconds: float

    @property
    def rate(self) -> float:
        return self.per_window / self.window_seconds


#: Signup is the enumeration path. Five in five minutes is more than anybody
#: creating one account needs and useless for a scrape — at this rate reading a
#: thousand-address list takes a fortnight per source address.
SIGNUP = Limit(per_window=5, window_seconds=300.0)

#: Sign-in leaks nothing (the failure text is identical for an unknown address
#: and a wrong password) so this is about password guessing, not enumeration.
#: Looser, because a person mistyping a password three times is ordinary.
SIGNIN = Limit(per_window=10, window_seconds=300.0)

#: Confirmation codes are six digits. Without a bound, guessing one is minutes.
CONFIRM = Limit(per_window=8, window_seconds=600.0)


class Throttled(Exception):
    """Refused for rate, with the wait intact so a surface can say how long."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = max(1, int(retry_after))
        super().__init__(f"Too many attempts. Try again in {self.retry_after} second(s).")


@dataclass
class _Bucket:
    tokens: float
    last: float


class Throttle:
    """Token buckets keyed by caller and action.

    Deliberately not a decorator. A decorator hides *which* identifier is being
    counted, and the whole correctness of this rests on that: keyed by an
    address a caller cannot choose, never by the email being asked about — which
    would let one attacker walk a list at full speed by never repeating a value.
    """

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._guard = threading.Lock()

    def check(self, action: str, caller: str, limit: Limit, *, now: float | None = None) -> None:
        """Spend one token or raise. Call before doing the work, not after."""
        moment = time.monotonic() if now is None else now
        key = (action, caller)
        with self._guard:
            bucket = self._buckets.get(key)
            if bucket is None:
                self._buckets[key] = _Bucket(tokens=limit.per_window - 1, last=moment)
                return

            bucket.tokens = min(
                float(limit.per_window),
                bucket.tokens + (moment - bucket.last) * limit.rate,
            )
            bucket.last = moment
            if bucket.tokens < 1:
                raise Throttled((1 - bucket.tokens) / limit.rate)
            bucket.tokens -= 1

    def state(self) -> dict:
        """What this bound actually is, for a surface that must not overstate it."""
        with self._guard:
            return {
                "scope": "this process",
                "shared_across_tasks": False,
                "tracked": len(self._buckets),
            }

    def forget(self, action: str, caller: str) -> None:
        """Drop a caller's bucket after a *successful* action.

        A person who signs in on the third try should not be a step closer to a
        lockout for the rest of the window. Only ever called on success, so it
        cannot be used to reset a bucket by failing.
        """
        with self._guard:
            self._buckets.pop((action, caller), None)


#: One per process. Module-level because the bound is about the process.
THROTTLE = Throttle()


def caller_of(request) -> str:
    """Who to count against.

    `X-Forwarded-For`'s *left-most* entry is the client as the load balancer saw
    it; anything further right was appended by proxies in between. Trusted only
    because nothing but the ALB can reach this port — the task security group has
    one ingress rule and it names the balancer's group. Read from
    `request.client` otherwise, so a local run counts by socket.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = getattr(request, "client", None)
    return getattr(client, "host", "") or "unknown"
