# docs — index

Read order for a new session: [CLAUDE.md](../CLAUDE.md) → [STATUS.md](../STATUS.md) → whichever
document below answers the question in front of you.

| # | Document | Answers |
|---|---|---|
| 00 | [Research dossier](00-RESEARCH-DOSSIER.md) | Why this problem. What the securo and qm code graphs showed. Benchmarks, OSS, the LLM-arithmetic evidence. |
| 01 | [Decision spec](01-DECISION-SPEC.md) | Problem, existing solutions, our solution, user flow, impact, trade-offs. The approve-or-reject document. |
| 02 | [Architecture addendum](02-ARCHITECTURE-ADDENDUM.md) | Why deterministic verification does not constrain intake. Proof tiers P0–P3. The MCP substrate. **Amends 01 §3 and §7.** |
| 03 | [Build plan](03-BUILD-PLAN.md) | Ten phases with gates, the Python stack with per-choice risk, model config and cost, 26 named failure modes. |
| 04 | [Control-plane audit](04-CONTROL-PLANE-AUDIT.md) | Five reproducible bypasses found by attacking the system at P5, the single root cause, and the three-trust-class redesign. **Blocks P7.** |
| 05 | [Failure register](05-FAILURE-REGISTER.md) | 19 probes: where a novel input crashes, finishes silently, or finishes wrong — plus invariant 8 and the disposition ladder that routes every case. |
| 06 | [Plan v2](06-PLAN-V2.md) | **The working plan.** P6–P15 re-planned after the audits: control plane before the agent, decision log earlier, ship line at P10. Supersedes 03 from P6 onward. |
| 07 | [Architecture audit](07-ARCHITECTURE-AUDIT.md) | The root cause: the certifying-algorithm discipline is applied to one decision type out of five. Graph + runtime tracing + five experiments. |
| 08 | [As built](08-AS-BUILT.md) | The flow that **runs today** — input, processing, output — what a customer gets, and what is missing. Read beside 01's §4, which is the flow we intend. Revised when P13/P14 landed a product surface. |
| 09 | [Product direction](09-PRODUCT-DIRECTION.md) | **PROPOSED, not approved.** The user journey, screen map, design system, auth and AWS deployment for the product surface. Nothing in §§2–6 is built. |
| 10 | [The user flow](10-THE-USER-FLOW.md) | What a controller actually does with this, with the real numbers from batch A — and the four things missing, the largest being that an attested exception leads to no disposition. |
| 11 | [What happens next](11-WHAT-HAPPENS-NEXT.md) | How many documents this engine can reconcile (two sides, any number of files), what practitioners expect after the match — ageing, suspense, preparer≠reviewer, a tax-deduction code we lack — and the one flow to build. |
| 12 | [Signing in](12-AUTH.md) | The confirmation screen that did not exist, and what splitting sign-in from create-account costs: one enumeration oracle, bounded rather than hidden. |
| 13 | [The screens](13-THE-SCREENS.md) | The journey start to finish, one question per screen, and the five rules they follow — plus what is still rough. |
| — | [decisions/](decisions/) | ADRs. Two are irreversible: [ADR-001](decisions/ADR-001-declarative-adapters.md) declarative adapters, [ADR-002](decisions/ADR-002-semver-contracts.md) semver'd contracts. |

## Running it

Two surfaces, both real since 2026-08-25. Neither is a benchmark.

```bash
make serve   # http://127.0.0.1:8000/ — close a period, work the tail, export the audit
             # http://127.0.0.1:8000/docs — OpenAPI, with the semver'd contracts in it
make mcp     # 16 tools on stdio, for an agent
```

`POST /v1/verify` (and the MCP `verify_proof`) is the one call worth knowing: it is stateless and
public. Hand it a proof out of an audit export and records you ingested yourself from the source
files, and it re-derives the arithmetic under a policy you name. No account, no database, no reason
to trust us — see [08-AS-BUILT.md](08-AS-BUILT.md).

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
| Five Ways Past the Gate | https://claude.ai/code/artifact/20d9bec6-36ef-4f70-bd87-278812c1ab80 | `04-CONTROL-PLANE-AUDIT.md` |
| Where the Run Goes Quiet | https://claude.ai/code/artifact/f23cb3b6-be3a-400b-9be4-999162743893 | `05-FAILURE-REGISTER.md` |
| The Route From Here | https://claude.ai/code/artifact/b43c41e6-fd0a-4fb8-8422-bd0c327b14a8 | `06-PLAN-V2.md` |
| Glass and Evidence | https://claude.ai/code/artifact/22e06f61-e217-4959-943c-692dffd14479 | `09-PRODUCT-DIRECTION.md` |
| FinCon Clear Ledger | https://claude.ai/code/artifact/97d639ef-32e1-470d-bd84-e5604ab44f8b | the design system, rendered live — no markdown mirror |

The walkthrough has no markdown mirror in this repo; its numbers are illustrative and internally
consistent (verified with a script at authoring time), not measurements. Real numbers come from
`make eval`.

## What the numbers currently say

Measured, not projected. Regenerate with `python -m bench.run --batch A`.

```
blocking: 150/506 pairs (70.4% reduction) :: amount=123 date=200 reference=19
          blocking recall 100.0% (21/21 reachable true pairs kept);
          1 true pair not reachable at all — the source declared no group

arm               auto-match  false-match  precision   recall  correct  false  missed  unprovable
securo_raw             0.0%       0.00%      0.0%    0.0%        0      0      22           0
securo_grouped        86.4%       0.00%    100.0%   86.4%       19      0       3           0
deterministic         90.9%       0.00%    100.0%   90.9%       20      0       2           1

arm               raised   coverage      classification   ambiguity
securo_grouped         0    0.0% (0/6)      0.0% (0/6)    0.0% (0/1)
deterministic          7  100.0% (6/6)     66.7% (4/6)  100.0% (1/1)
```

**The finding that stood from P3 to 2026-08-25:** handed the payout grouping, securo's 1:1 rule
produced pairs *identical* to ours, and the match rate was not the differentiator. The
partial-payment strategy is the first thing to break that tie, and it breaks it by exactly one
pair — the short-paid payout, which securo cannot match because the amounts disagree. Pinned as
`gate_p3.py::test_our_matching_rule_beats_the_fair_baseline_by_exactly_one_declared_pair`, which
asserts the difference is exactly one and that the extra pair is the declared one.

**The claim is unchanged in shape.** One pair on matching; everything on the tail — coverage
100% against 0%, classification 66.7% against 0%, ambiguity 100% against 0%, because a matcher
with no exception model scores zero on all three by construction. The one unprovable match is the
partial payment, and it is declared: the count that must stay at zero is the *undeclared* ones.
