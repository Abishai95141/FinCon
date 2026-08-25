# The Route From Here — plan v2

Date: 2026-08-21 · Supersedes the phase plan in [03-BUILD-PLAN.md](03-BUILD-PLAN.md) from P6 onward.
P0–P5 are green and unchanged; their gates and evidence stand.

## Why re-plan

The original plan put governance nowhere. Approval gates were a bullet inside P7, events a bullet
inside P8, and policy did not exist as an object at all. Two audits at P5 —
[04-CONTROL-PLANE-AUDIT.md](04-CONTROL-PLANE-AUDIT.md) and
[05-FAILURE-REGISTER.md](05-FAILURE-REGISTER.md) — showed what that costs: five control bypasses and
ten failure cases, all of them the same missing layer.

Running the old P6 next would measure a system whose governance is known-broken. Running the old P7
next would put a model on a foundation with five bypasses in it. So the control plane becomes phases
of its own, ahead of both.

### Mapping from the old plan

| Old | New | Changed how |
|---|---|---|
| P6 ablation runner ◆ | **P10** | Unchanged in content; moved behind the control plane so it measures a governed system |
| P7 model edge ◆ | **P12** | Unchanged in content; now lands on a foundation with no known bypass |
| P8 MCP + events | **P9** (events) + **P13** (MCP) | Split. The decision log moves *earlier* — you cannot audit an agent you did not log. |
| P9 screens | **P14** | Unchanged |
| P10 second loop | **P15** | Now paired with the declarative pipeline, which is what makes a second loop configuration rather than code |

---

## Ordering principle

Three rules decided the sequence, in priority order.

1. **What catches unknown failures comes before what fixes known ones.** The completeness audit is
   first because it is the only item on either audit list that finds cases nobody enumerated.
2. **Governance before the agent.** A model authoring configuration on top of five bypasses would
   build the demo that proves the opposite of the thesis.
3. **Measurement before the agent.** The lift number needs a governed baseline to be a lift *from*.

---

## The plan

### P6 — Completeness and honest failure
No crash, no silence. Small, no dependencies, highest value on the list.

- [ ] **Completeness audit — invariant 8.** At end of run, assert every source, record and anchor has
      a disposition, computed independently of the code paths that produced them.
- [ ] **Readers report instead of raising.** Return a failed `IntakeProof`; makes `ingest()`'s
      docstring true and stops one bad file killing a close.
- [ ] **A source producing zero records fails** regardless of row count.
- [ ] **`UNMAPPABLE` verb outcome** carrying column name and three sample values.

**Gate:** the four crash cases and three silent cases from the register each produce a disposition
instead. A deliberately undisposed anchor makes the completeness audit fail — asserted directly, so
the audit is not decorative. `make verify` still green on P0–P5.

*Why here:* invariant 8 would have found both silent matching cases without anyone writing a
partial-payment test. Everything after this is a known hole with a known fix; this is the one that
finds the unknown ones.

### P7 — Policy and the constraint layer
The single change that closes both critical bypasses.

- [ ] **`Policy` contract** — versioned, human-owned, signed, supplied out-of-band.
- [ ] **`verify(proof, records, policy)`** replaces `verify(proof, records, side_signs)`. The proof's
      declared tolerance becomes a claim checked against policy, not a permission honoured.
- [ ] **`MatchProfile` validators** — signs must be ±1, tolerance must sit under the policy ceiling.
- [ ] **Rejection budget** in policy; intake fails above it rather than reporting `declared`.
- [ ] **Rounding threshold** in policy; residue above it becomes `E03`, below it posts to the
      rounding account and is recorded.

**Gate:** every attack in the audit is reproduced as a failing test first, then turned green. `F1`
(forged tolerance), `F2` (zero signs), `F4` (rejection volume), sub-paisa drift. A proof that passed
verification before P7 and should not have must now be refuted.

### P8 — The promotion gate
Blocks rule induction. Must land before anything authors a rule.

- [ ] **Regression gate v2** — count matches **added** as well as broken; re-run the regression under
      current policy rather than trusting the report shipped with the rule; cap the match delta by
      policy; require a sample of added matches in the approval.
- [ ] Promotion becomes an **event**, not a field: actor, policy version, evidence hash.

**Gate:** the `R-EVIL` rule from the audit — tolerance to ₹1,000,000, 0 broken, 93 cleared — is
**refused**. A legitimate narrow rule still promotes.

### P9 — The record
Moved earlier from the old P8. You cannot audit an agent you did not log.

- [x] **Append-only decision log**, typed events: `MatchProven`, `MatchRejected`, `ExceptionRaised`,
      `RuleInduced`, `RulePromoted`, `AdapterAuthored`, `IntakeUnverified`, `CloseBlocked`,
      `ProposalRefused`, `CodeProposed`. Plus five the replay needs: `CloseStarted`,
      `SourceIngested`, `OutOfScope`, `PostingWritten`, `CloseCompleted`.
- [x] Every event carries actor, input hash, policy version, outcome.
- [x] *Added:* the close posts, and the completeness audit covers postings — closing the gap P6
      left open. A decision log for a reconciliation that never reached the books is half a log.

**Gate:** replay a full close from the log alone and reconstruct the same scorecard. An event stream
that cannot reproduce the run is not an audit trail. **GREEN 2026-08-24** — evidence in STATUS.md.

### P10 — Measurement ◆ SHIP LINE
The old P6, unchanged in content. Everything after this is upside.

- [x] `make eval` — one command, batches A and B, the eight metrics.
- [x] Arms: securo_raw, securo_grouped, deterministic. The LLM-only arm reports **absent**, not zero
      — a zero reads as "it tried and failed".
- [x] Every rate ships with its decomposition; the renderer makes omitting it awkward.

**Gate:** full comparison table from a clean checkout, one command. **GREEN 2026-08-24** — taken
before P9 at the user's direction; safe in this order because P9's gate is "reconstruct the same
scorecard", and until P10 there was no canonical scorecard to reconstruct. Evidence in STATUS.md.

### P11 — Open taxonomy
Before the agent, because the agent needs to be able to name a novel finding without crashing.

- [x] **Exception-code registry** with a lifecycle replacing the closed enum:
      `PROPOSED → PROVISIONAL → PROMOTED → RETIRED`.
- [x] `PROPOSED` may label and route; **cannot fire a rule or affect a posting**.
- [x] Contract **major bump** — breaking. Do it while there are no external consumers.
- [x] *Added:* the deterministic worklist — ranked by cash impact × age, routed by the registry.
      Ranking and routing need no model; what an exception *is* stays P12's problem.

**Gate:** a novel finding gets a `PROPOSED` code, appears in triage, routes to an owner, and is
proven unable to affect a posting. Promotion requires a named human and a written definition.
**GREEN 2026-08-24** — evidence in STATUS.md.

### P12 — The model edge ◆ THE LIFT NUMBER
The old P7. Not cuttable — without it there is no agent and no lift.

- [x] **Adapter-spec synthesis** — declarative spec only, no codegen (ADR-001), first-use approval.
      *(2026-08-24: built. A source in a format never seen is read, a spec authored, verified and
      ingested with no configuration. The spec cannot name its own author or approve itself, and a
      verb outside the vocabulary is a validation error rather than an attempt — `gate_p12c`.)*
- [x] **Exception triage** — classify into the registry, hypothesis, cited evidence, rank by cash
      impact × age. *(2026-08-24: built on `deepseek-v4-flash`. Classification 20% → 40% on A and
      held-out B. A proposal may not overwrite a code the engine derived by proof — found by
      measuring a net lift of zero on the first pass.)* Proposing a new code is wired in P11 and
      not yet driven from triage.
- [x] **Rule induction** — proposal + regression report through the P8 gate. *(2026-08-25:
      `R-DUP-06` is promoted and shipping — `raise_advisory -> E06` on a repeated export row,
      classification 1/5 → 2/5 on A **and** on held-out B, no false match, no value moved. Two
      refusals came first, both correct: a rule that suppressed the duplicate was strictly harmful
      (a false match, and the planted E06 destroyed for the exact value it removed), and an advisory
      naming no code re-coded nothing. Behind them, promotion had never had an effect at all — three
      of five actions could promote and do nothing.)*

**Gate:** resolve three exceptions on batch A, approve three induced rules, re-run on held-out batch
B, and the scorecard attributes the improvement rule by rule. Plus: drop a source in a format never
seen and watch it author, verify and ingest without configuration. **RED at 2026-08-25** — all
three parts are built and the unseen-format half of the gate is met. What is missing is the *count*:
one rule is promoted, not three, so there is no rule-by-rule attribution table yet. Two things bound
it, both named — there is no attestation path for a resolution that removes value, and predicates
are single-record, so `E02` ("billed above contract tier", a fee compared against a rate on another
record) is inexpressible. Evidence in STATUS.md.

### P13 — Substrate
The old P8's other half.

- [ ] FastMCP server over the kernel; every mutating tool returns a proof or a proposal.
- [ ] **`verify_proof` as a stateless public call** — takes policy, so an external caller re-derives
      under the same constraints we do.
- [ ] Typed events published.

**Gate:** an external process calls `run_match`, then re-derives the returned proof without touching
our database — and a forged proof is refused by that same public call.

### P14 — Surface
- [ ] Scorecard with the proof-tier breakdown and blocking recall.
- [ ] Exception worklist, proof expandable per row.
- [ ] Audit export: every decision with proof, rule version, approver.

**Gate:** a controller completes one close through the UI without a terminal.

### P15 — Generality
- [x] **Declarative strategy pipeline** — the profile declares its strategies in order; a strategy
      takes anchor + candidates + policy and returns a proposal, and cannot post or verify.
      *(2026-08-25: `engine/strategies.py`, a closed registry; an unknown name is a profile error
      before a close begins. Verified by byte-identical `outcome_digest` on both batches.)*
- [ ] **Partial-payment and 1:N strategies** as the first two things added *as configuration*.
      **BLOCKED on evidence, not on code.** `E04` is in neither the adversarial set nor the
      generator, so there is nothing to run against. Authoring it now — knowing what this engine
      handles — is authoring and solving in one motion, which the ban table forbids. Doable
      honestly (author red first, label the provenance as later than P0, implement second); that
      is a decision about evidence and needs to be made deliberately.
- [ ] **Second loop — GSTR-2B** with zero kernel code changed. **Nothing exists**: no profile, no
      generator, no adapters, no data. This is a second P0, not a P15 afternoon.

**Gate:** a second loop closes on profile and adapters alone. Partial payment goes from "raises an
exception" (P6) to "matches with a proof" without an engine edit.

---

## Cut order under time pressure

P15 first, then P14 (demo from the CLI), then P13. **P6 through P10 are not cuttable** — they are the
difference between a measured system and an asserted one. **P12 is not cuttable for the claim**; the
system ships without it but the thesis does not.

If P11 overruns, ship P12's triage against the closed enum with a hard `UNMAPPABLE` escalation for
findings that do not fit, and say so.

---

## What this plan still does not cover

Named so it is not mistaken for complete. No concurrency story. No multi-tenant isolation test. No
adversarial fixture for prompt injection through file content — it is argued-safe by architecture
(no egress, no ledger write path) and **untested**. FX is deferred to a single functional currency.
A source that changes format mid-file is unhandled. And every audit behind this plan is one person
probing their own design.
