# docs — index

Read order for a new session: [CLAUDE.md](../CLAUDE.md) → [STATUS.md](../STATUS.md) → whichever
document below answers the question in front of you.

| # | Document | Answers |
|---|---|---|
| 00 | [Research dossier](00-RESEARCH-DOSSIER.md) | Why this problem. What the securo and qm code graphs showed. Benchmarks, OSS, the LLM-arithmetic evidence. |
| 01 | [Decision spec](01-DECISION-SPEC.md) | Problem, existing solutions, our solution, user flow, impact, trade-offs. The approve-or-reject document. |
| 02 | [Architecture addendum](02-ARCHITECTURE-ADDENDUM.md) | Why deterministic verification does not constrain intake. Proof tiers P0–P3. The MCP substrate. **Amends 01 §3 and §7.** |
| 03 | [Build plan](03-BUILD-PLAN.md) | Ten phases with gates, the Python stack with per-choice risk, model config and cost, 26 named failure modes. |
| — | [decisions/](decisions/) | ADRs. Two are irreversible: [ADR-001](decisions/ADR-001-declarative-adapters.md) declarative adapters, [ADR-002](decisions/ADR-002-semver-contracts.md) semver'd contracts. |

## Published artifacts

Rendered versions of the documents above, shareable with people who will not clone the repo.
**These URLs live nowhere else** — the conversation that produced them is not durable.
Republishing to the same URL requires passing it as `url` to the Artifact tool.

| Artifact | URL | Mirrors |
|---|---|---|
| Propose, Verify, Prove | https://claude.ai/code/artifact/8c830043-06ac-4f09-94b5-0692a954dced | `00-RESEARCH-DOSSIER.md` |
| The Exception Tail | https://claude.ai/code/artifact/b12b2971-5c62-45fa-a10d-b3c7356106e8 | `01-DECISION-SPEC.md` |
| Open Intake, Verified Commit | https://claude.ai/code/artifact/5ec82d14-b5d0-437a-8834-d11dc4861adc | `02-ARCHITECTURE-ADDENDUM.md` |
| One Close, End to End | https://claude.ai/code/artifact/7b3e968e-888c-419c-bdf4-9729e32b228a | walkthrough — no markdown mirror |
| Build Order and Blast Radius | https://claude.ai/code/artifact/ee939959-bd65-471c-a4fe-992687fe1fbf | `03-BUILD-PLAN.md` |

The walkthrough has no markdown mirror in this repo; its numbers are illustrative and internally
consistent (verified with a script at authoring time), not measurements. Real numbers come from
`make eval`.

## What the numbers currently say

Measured, not projected. Regenerate with `python -m bench.run --batch A`.

```
blocking: 146/484 pairs (69.8% reduction)
          blocking recall 100.0% (21/21 reachable true pairs kept);
          1 true pair not reachable at all — the source declared no group

arm               auto-match  false-match  precision   recall
securo_raw             0.0%       0.00%       0.0%      0.0%
securo_grouped        90.9%       0.00%     100.0%     90.9%
deterministic         90.9%       0.00%     100.0%     90.9%
```

The finding to carry forward: **handed the payout grouping, securo's 1:1 rule produces pairs
identical to ours.** The match rate is not the differentiator. That is the decision spec's thesis
confirmed from our own data, and it is pinned as a test
(`gate_p3.py::test_our_matching_rule_does_not_beat_the_fair_baseline`).
