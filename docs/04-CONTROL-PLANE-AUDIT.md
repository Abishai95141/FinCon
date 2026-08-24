# Five Ways Past the Gate — control-plane audit

Date: 2026-08-21 · System state: P5, 104 tests green, six gates passed
Published: https://claude.ai/code/artifact/20d9bec6-36ef-4f70-bd87-278812c1ab80

Every finding is a run, not a reading. I attacked the working system rather than reviewing it,
asking: *if a model were authoring the configuration this system already accepts, what could it get
past — not through a bug, but through the interfaces as designed?*

---

## Findings

### F1 · CRITICAL — a proof declares its own permission

`verify()` checks `abs(residual) > proof.tolerance_allowed`, reading the tolerance **out of the
proof it is verifying**.

```
dropped 2 settlement rows from a real proof, residual = ₹7,466.19
declared  tolerance_allowed = 9999999.00
verdict:  PROVEN
```

This undermines the load-bearing claim of the whole substrate argument — that a third party can call
`verify_proof` and re-derive our arithmetic without trusting us. Today they get `PROVEN` on a forged
proof. The verifier checks that a proof is *internally consistent*, never that it was *permitted*.

Missing verb: **constrain**.

### F2 · CRITICAL — the sign convention comes from the caller

`verify(proof, records, side_signs)` takes its arithmetic convention as an argument. The only
production call site passes `profile.side_signs` — the profile an agent would author. `MatchProfile`
has **zero validators**, so nothing requires signs to be ±1.

```
verify(proof, records, {"bank": 0, "settlement": 0})
residual = 0.00   verdict: PROVEN
```

Every match verifies, forever, for any records. The verifier's own docstring says signs come from
the caller "never from the proof" so a proof cannot choose its own convention — right instinct,
aimed one layer too high. The caller is not trusted either.

Missing verb: **validate**.

### F3 · HIGH — the regression gate is blind to the failure it exists to stop

`RegressionReport.promotable` is `matches_broken == 0`. Widening a tolerance never *breaks* an
existing match; it only adds new ones. The gate measures the one direction that cannot detect the
danger.

```
rule R-EVIL  action: set_tolerance → ₹1,000,000.00
regression:  0 broken, 93 exceptions would clear
promotable:  True   → contract accepted PROMOTED
```

Every governance story for rule induction rests on this gate. A model optimising for "exceptions
cleared" finds this move immediately, and it looks like excellent performance.

Missing verb: **validate**.

### F4 · HIGH — row conservation permits discarding half the file

The check asks whether every departing row carried a reason, not whether the departures were
justified.

```
added: reject rows where row_type matches "FEE", reason "fees_are_not_settlement_rows"
parsed 266 / rejected 251 of 517     row_conservation = pass
strength = declared                  ok = True
```

Reported as `declared`, which downstream reads as "weakly evidenced", not "we threw away 251 rows".
The same attack on `bank_icici.csv` *was* caught — but only because roll-forward had a running
balance to break. The defence is a property of the source, not of the system.

Missing verb: **constrain**.

### F5 · MEDIUM — a missing verb fails plausibly, not loudly

A source carrying amounts as integer minor units parsed cleanly and was **100× wrong**; every check
passed or skipped because it had no control total to contradict it. Fixed by adding `DECIMAL_MINOR`
(contract 1.3.0), but the class is permanent: a closed vocabulary lacking the right verb does not
refuse — it picks the nearest and returns a plausible number.

Missing verb: **escalate** — "no verb fits" has no way to be said.

### Rigidity that is not exploitable but blocks the agentic case

| Where | What is fixed | What it costs an agent |
|---|---|---|
| `engine/tiers.py` | Tier sequence is a literal tuple `(T0, T1)`, T2 hard-wired after | A new strategy has nowhere to go. The workflow is code, not configuration. |
| `contracts/exception.py` | 13 codes, closed enum | A novel finding cannot be named. Force-fitting is worse than silence, because rules key on codes. |
| `engine/blocking.py` | Three block shapes | A source needing a fourth has no extension point. |
| `engine/tiers.py` | `MatchProfile` has no validators | Everything domain-specific is unchecked config — the surface F2 walks through. |
| whole repo | Approval, audit, escalation exist as contract *fields* with no enforcement code | There is no control plane. There is a vocabulary for one. |

---

## Root cause

**The system checks artifacts against themselves, and takes its policy from whoever calls it.**

A proof carries its own tolerance. The verifier takes its signs from the caller. An adapter declares
its own rejections. A rule ships its own regression report. Every check is rigorous about internal
consistency and silent about whether any of it was allowed.

Survivable while a human writes every config by hand — which is the situation today, with zero model
code in the repo. It stops being survivable the moment an agent authors the configuration, because
**every input the checks trust is an input the agent would be writing.**

The fix is not more rigidity — rigidity is what makes the closed taxonomy and hard-wired sequence
unable to absorb novelty. The fix is to separate what is negotiable from what is not, and make the
non-negotiable part something the agent cannot supply.

---

## Three trust classes

| Kernel — immutable | Policy — human-owned | Proposals — agent-authored |
|---|---|---|
| Enforced in code, no override, no flag. If configuration can turn it off it does not belong here. | Versioned, signed, supplied out-of-band. The answer to "was this allowed?". Never read from an artifact. | Unbounded, and powerless until checked against policy and recorded. |
| Residual arithmetic over Decimal · no `eval` · row-conservation identity · double-entry balance · append-only log | Tolerance ceilings · sign conventions · rejection budgets · account map · approval thresholds · which codes may fire a rule | Adapter specs · match profiles · induced rules · classifications · new code proposals |

The agent's freedom is the whole right-hand column, and it gets **wider** than today — profiles and
codes move into it. What changes is that nothing in that column reaches the ledger without passing
the middle one.

**The single most important signature change:** `verify(proof, records, side_signs)` becomes
`verify(proof, records, policy)`. Policy carries the sign convention and the tolerance ceiling; the
proof's declared tolerance becomes a *claim to check against policy* rather than a permission to
honour. F1 and F2 both close on this one change.

---

## Making novelty safe instead of impossible

**Open taxonomy with a lifecycle.** Replace the closed enum with a registry where a code has a state:

```
PROPOSED     agent wrote it. Visible in triage. Cannot fire a rule or touch a posting.
PROVISIONAL  a human acknowledged it. May group and route work. Still cannot post.
PROMOTED     a human accepted it, with a written definition. Full rights.
RETIRED      superseded; historical decisions keep their original code.
```

This resolves the flexibility objection without a bypass: **the agent can always name a new thing,
and the name has no power until someone grants it.**

**Declarative pipeline.** The profile declares its strategies in order. A strategy implements one
contract — anchor + candidates + policy → proposal + proof — and cannot post.

**Regression gate v2.** Counts matches broken *and added*; re-runs under current policy rather than
trusting the shipped report; widening actions require every added match to verify under policy, the
delta capped by policy, and a sample shown to the approver; promotion becomes an event with actor,
policy version and evidence hash.

**Rejection budget.** Policy sets a max rejection rate per source. Above it, intake *fails* rather
than reporting `declared`.

**Say "I don't know" out loud.** The vocabulary needs an `UNMAPPABLE` outcome so an agent that
cannot express a field returns "no verb fits, here is the column and three samples" and escalates,
rather than reaching for the nearest verb.

---

## The control plane, as six verbs

| Verb | Must do | Today |
|---|---|---|
| **validate** | Every proposal checked against schema *and* policy before effect | Schema only. Policy does not exist as an object. **F2, F3** |
| **constrain** | Ceilings the proposal cannot raise: tolerance, rejection rate, match delta | Ceilings live inside the artifacts they bound. **F1, F4** |
| **approve** | Named human consent on anything widening permission, evidence attached | Contract fields, no enforcement |
| **execute** | Only the kernel writes; proposal re-checked at execution against current policy | Engine both decides and writes; no re-check |
| **escalate** | A path for "I cannot express this" and "this needs judgement", with owner and due date | `E09`/`E13` escalate well; nothing else can |
| **record** | Append-only log: actor, input hash, policy version, outcome, per transition | Nothing. Proofs are the only durable evidence. |

**The answer to the question:** the architecture *can* support a genuinely agentic workflow while
staying governed — but not as built. What exists is a strong verification kernel and a vocabulary
for governance, with no control plane behind it. The five findings are the same missing layer
showing through in five places.

---

## Remediation order

| # | Change | Closes | Cost |
|---|---|---|---|
| 1 | `Policy` as a versioned object; `verify()` takes it instead of `side_signs` | F1, F2 | Small |
| 2 | Validators on `MatchProfile` — signs ±1, tolerance under the policy ceiling | F2 | Trivial; should have existed at P1 |
| 3 | Rejection budget in policy; intake fails above it | F4 | Small |
| 4 | Regression gate v2 | F3 | Medium — **blocks P7** |
| 5 | Append-only decision log with typed events | record | Medium; was P8, belongs earlier |
| 6 | Open code registry with lifecycle | rigidity | Medium; contract-breaking, major bump |
| 7 | Declarative strategy pipeline | rigidity | Larger; defer until a second loop needs it |

**One through four are not optional before P7.** P7 is where a model first authors configuration,
and every finding is a hole that only matters once something other than a human fills in the forms.
Shipping the agent onto this foundation would be building the demo that proves the opposite of the
thesis.

---

## What this audit does not cover

I attacked the interfaces I built, so it is biased toward failures I can imagine. Prompt injection
through file content is argued-safe by architecture (no egress, no ledger write path) but
**untested** — there is no adversarial fixture. Multi-tenant isolation has no test. And this is one
person auditing their own design, the same limitation flagged for the generator and engine at P0.
