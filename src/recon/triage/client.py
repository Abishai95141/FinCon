"""The model edge. One place, and it can only do one thing.

Everything a model produces in this system arrives through `propose()`, and
`propose()` returns a dict that matched a schema *we* wrote or it raises. There
is no prose path. That is not a stylistic preference:

**ADR-001 says no generated code is executed.** The security argument rests on
the model emitting declarative data a fixed interpreter reads. A prose fallback
— "if the tool call is missing, parse the text" — reintroduces exactly the thing
the ADR removed, one `except` block at a time. So a reply that is not a tool
call is a refusal, recorded and raised.

**CLAUDE.md rule 1 bans mocking the model and reporting agent metrics.** The
lift number is the claim, so there is no mock, no canned response and no replay
switch in this module. The gate asserts that structurally, because a mock that
exists will eventually be switched on by someone in a hurry.

Every call records what it cost. An edge that cannot say what it spent cannot
be audited for what it spent, and "cheap" is a claim like any other.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

#: Never anything else. A model that may decline to use the schema will decline
#: on exactly the inputs that are hardest, which is where the schema mattered.
SCHEMA_TOOL_CHOICE = "required"

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"


#: Attempts per call. Three because a rate limit clears in seconds and a
#: provider outage does not clear at all — more attempts would turn a dead
#: endpoint into a slow one, which is harder to notice.
RETRIES = 3

#: First wait, doubled each attempt.
BACKOFF_SECONDS = 1.5

#: Statuses worth trying again. 429 is a rate limit and 5xx is the provider;
#: everything else is our request and will fail identically forever.
TRANSIENT_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class ModelUnavailable(Exception):
    """The edge could not be reached. Distinct from a refusal: a network failure
    is a fact about us, not about the proposal, and reporting one as the other
    is the `E13` mistake in a different layer."""


class ProposalRefused(Exception):
    """The model replied, and the reply is not usable as a proposal."""


@dataclass(frozen=True)
class ModelCall:
    model: str
    tool_name: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    elapsed_ns: int
    ok: bool
    refusal: str | None = None


@dataclass
class ModelEdge:
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    api_key: str | None = None
    max_tokens: int = 600
    timeout_s: int = 90
    calls: list[ModelCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ModelUnavailable(
                "DEEPSEEK_API_KEY is not set. The model edge has no offline mode "
                "by design — see CLAUDE.md rule 1 on mocking the model."
            )

    # -- request shaping ---------------------------------------------------

    def request_body(
        self, *, system: str, user: str, tool_name: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Built here rather than inline so a gate can assert its shape without
        spending a call."""
        return {
            "model": self.model,
            # Off deliberately. Triage is a classification against a written
            # registry, not a reasoning problem, and the thinking tokens are
            # the expensive half. Turn it on when a task needs it, per task.
            "thinking": {"type": "disabled"},
            "max_tokens": self.max_tokens,
            "tool_choice": SCHEMA_TOOL_CHOICE,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": "Emit one proposal. This is the only reply accepted.",
                        "parameters": schema,
                    },
                }
            ],
        }

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        # Bounded retries, on *transient* failures only. A rate limit or a 502
        # is the provider being busy and the same request will work in a moment;
        # a 400 is a request that will never work and retrying it three times
        # just spends three times as long being wrong.
        #
        # Deliberately **not** retried: a reply that is not a tool call. That is
        # `ProposalRefused`, raised further up, and it is a finding about the
        # model rather than a network event — retrying until it complies would be
        # ADR-001 dismantled by patience instead of by an `except` block.
        last: Exception | None = None
        for attempt in range(RETRIES):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as exc:
                detail = f"HTTP {exc.code}: {exc.read()[:200]!r}"
                if exc.code not in TRANSIENT_STATUS:
                    raise ModelUnavailable(detail) from exc
                last = ModelUnavailable(detail)
            except OSError as exc:
                last = ModelUnavailable(f"{type(exc).__name__}: {exc}")
            if attempt < RETRIES - 1:
                time.sleep(BACKOFF_SECONDS * (2**attempt))
        raise ModelUnavailable(f"{RETRIES} attempts failed; last was {last}") from last

    # -- the only way a model speaks ---------------------------------------

    def propose(
        self, *, system: str, user: str, tool_name: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        body = self.request_body(system=system, user=user, tool_name=tool_name, schema=schema)
        started = time.perf_counter_ns()
        payload = self._post(body)
        elapsed = time.perf_counter_ns() - started

        usage = payload.get("usage", {}) or {}

        def record(ok: bool, refusal: str | None) -> None:
            self.calls.append(
                ModelCall(
                    model=self.model,
                    tool_name=tool_name,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    cached_tokens=usage.get("prompt_cache_hit_tokens", 0),
                    elapsed_ns=elapsed,
                    ok=ok,
                    refusal=refusal,
                )
            )

        choice = (payload.get("choices") or [{}])[0]
        if choice.get("finish_reason") != "tool_calls":
            reason = (
                f"NOT_A_TOOL_CALL: finish_reason={choice.get('finish_reason')!r} — "
                f"a reply that is not a tool call is refused, never parsed"
            )
            record(False, reason)
            raise ProposalRefused(reason)

        tool_calls = (choice.get("message") or {}).get("tool_calls") or []
        if not tool_calls:
            record(False, "EMPTY_TOOL_CALLS")
            raise ProposalRefused(
                "EMPTY_TOOL_CALLS: finish_reason claimed a tool call and none was present"
            )

        raw = tool_calls[0].get("function", {}).get("arguments", "")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            record(False, f"arguments are not JSON: {exc}")
            raise ProposalRefused(f"tool arguments did not parse: {exc}") from exc

        if not isinstance(parsed, dict):
            record(False, "arguments are not an object")
            raise ProposalRefused("tool arguments are not a JSON object")

        record(True, None)
        return parsed

    # -- what it cost ------------------------------------------------------

    def total_tokens(self) -> int:
        return sum(c.prompt_tokens + c.completion_tokens for c in self.calls)

    def spend_report(self) -> dict[str, Any]:
        """Tokens are measured. Money is **absent**, not zero and not estimated.

        `deepseek-v4-flash` publishes no rate through the API, so a rupee figure
        here would be a number we made up — the same failure as reporting an
        unmeasured arm as zero (P10). Fill `usd` in when a verified rate exists.
        """
        return {
            "model": self.model,
            "calls": len(self.calls),
            "refused": sum(1 for c in self.calls if not c.ok),
            "prompt_tokens": sum(c.prompt_tokens for c in self.calls),
            "completion_tokens": sum(c.completion_tokens for c in self.calls),
            "cached_tokens": sum(c.cached_tokens for c in self.calls),
            "elapsed_ms": sum(c.elapsed_ns for c in self.calls) // 1_000_000,
            "usd": None,
        }
