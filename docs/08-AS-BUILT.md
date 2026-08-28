# As built — the flow, the value, and the gap

Date: 2026-08-25, **revised the same day** when P13 and P14 landed. §2's output
table and §4's headline both changed materially: there is a product surface now.
`docs/01-DECISION-SPEC.md §4` describes the flow we *intend*. This describes the
one that **runs today**, so the two are never confused. Where they differ, the
difference is named rather than smoothed.

---

## 1. What the comparison repos were worth

**`formancehq/reconciliation`** — 112 Go files, graphed and read.

*Adopted, and shipped:* the **fingerprint**. They dedup alerts on
`(rule_id, fingerprint, period_id)` with `first_seen_at` and `occurrence_count`,
so a persisting break is one recurring case rather than N unrelated findings.
Ours was `EXC-00001` — a position in a list, naming a different finding in every
batch. `ReconException.fingerprint` is content-derived now, and two of seven
breaks are visibly recurring across A and B where nothing linked them before.

*Identified and not adopted, deliberately:*

| Theirs | Why not yet |
|---|---|
| `Rule.Revision` + jobs fenced at commit | We are batch, not continuous; nothing races a rule mid-close. The principle — work computed from an old definition may not overwrite the current one — is worth keeping in mind if that changes. |
| `Severity` on rules and alerts | Our taxonomy carries `owner` and `escalation_is_correct`, which routes. Severity would rank; the worklist already ranks by cash impact. Adding a second ranking axis with no evidence it helps is a knob, not a feature. |
| `Cadence` / period model | Needs the cross-close state we do not have. This is item 1 in `STATUS.md → Next action`. |
| Alert lifecycle: `Ack`, `Snooze`, `Resolution` | A workflow feature with no surface to drive it. There is a surface now (P14) and this is the first thing to reconsider — it needs the cross-close store, which is the row above. |

*The most valuable thing was not a feature.* Their `TemplateKind` is a typed
catalog of rule shapes that "compiles deterministically to an internal CEL
expression. The kernel is not exposed at V1 GA; templates are the entire
customer-facing surface. **See ADR-001**." That is our ADR-001, arrived at
independently, down to the document number. Their `TemplateSourceParity` — "two
independent records of the same money match" — is our `MatchProfile`. Two teams
solving this separately reached the same two load-bearing decisions.

**`juspay/hyperswitch`** — 2,095 Rust files, and **no reconciliation
implementation in the open-source tree**. What is there is a feature flag
(`is_recon_enabled`), permission-group migrations, and a `recon_status` enum: the
module itself is closed-source. The public docs are marketing-level — "99%
accuracy", "80% of exceptions resolved automatically" — with no architecture
behind them. Nothing to adopt, and saying so is more useful than manufacturing a
lesson. The one comparable is their error taxonomy: processing-fee mismatches,
chargebacks, refunds, duplicates — the same categories as our `E02`, `E07`,
`E06`.

---

## 2. The flow, as it actually runs

### Input

Two files per close, dropped on disk:

| Source | Format | Read by |
|---|---|---|
| Bank statement | CAMT.053 XML | `icici-camt` adapter spec |
| Gateway settlement | CSV | `gateway-settlement` adapter spec |

A **third leg — the order/invoice register — is declared out of scope** by the
profile and is not reconciled. The planted `E07` chargeback sits on it and is
scored separately, which is why coverage reads 6/6 rather than 7/7.

A source in a format never seen before does not need an adapter written by hand:
`triage/normalize.py` reads the file's structure and authors a declarative spec,
which is then verified and ingested. No code is generated or executed (ADR-001).

### Processing

```
ingest        five proofs per source — row conservation, control-total tie-out,
              balance roll-forward, type/domain validity, idempotence
              → a source that fails is DECLARED, never dropped

authority     data/policy, data/taxonomy, data/rules verified against a signature
              (Ed25519, key out of band) → recorded, trusted or not

block         candidate pairs by amount / date / reference (70% reduction here),
              with blocking recall reported so a dropped true pair cannot hide

match         the profile's declared strategy sequence, in order:
                exact → tolerant → partial_payment → subset_sum
              a promoted rule may suppress, re-code, re-book, normalise or widen —
              and its approval is checked against the policy in force before it acts

verify        every match re-derived from raw records by a checker that does not
              read the proof's own claims → an unverified match is not a match

detect        rows that disagree with their own population (E02), and anything
              left over dispositioned as an exception — never a silent non-match

post          double-entry journal, balance assertion against the bank's closing
              balance → doesn't balance, the close is BLOCKED, not warned

record        an append-only hash-chained decision log; the run refuses to finish
              if any input the completeness audit disposed of is named by no event
```

### Output

| Artifact | Where | Real today |
|---|---|---|
| Scorecard | terminal · **the screens** · `GET /v1/runs/{id}` | yes |
| Ranked, routed worklist | terminal · **the screens** · `GET /v1/runs/{id}/worklist` | yes |
| Decision log | `data/runs/<run_id>/decisions.jsonl` · `GET /v1/runs/{id}/events` | yes — 62 events for batch A |
| **Audit export** | `GET /v1/runs/{id}/export` | **yes** — every decision with its proof, rule version and approver, plus how to re-derive it |
| **Independent re-derivation** | `POST /v1/runs/{id}/reverify`, and a button on the page | **yes** |
| **Stateless public verification** | `POST /v1/verify` · MCP `verify_proof` | **yes** |
| **UI** | `make serve` → `http://127.0.0.1:8000/` | **yes** — server-rendered screens, no JavaScript |
| **MCP** | `make mcp` → 21 tools on stdio · `make mcp-http` over Streamable HTTP + OAuth | **yes** |
| Journal entries + balance assertion | `GET /v1/runs/{id}/journal` · CSV and beancount on the close pack | **yes** — and the beancount export is re-loaded by beancount itself, so a third party validates it |
| Cross-close history on a break | — | **not built** — `fingerprint` is the precondition and landed; the store does not exist |

**Two entry points, and neither of them is a benchmark any more.** `make serve`
starts the HTTP API and the screens; `make mcp` starts the MCP server. Both are
driving adapters over `recon.service`, and a property test asserts an HTTP body
and the corresponding MCP tool result are byte-identical, so "one code path" is
checked rather than claimed. `python -m bench.run` still exists and is now what
it always should have been: a harness that scores the product against labels
nobody has in production.

**What the surface refuses, structurally.** No route and no tool schema accepts
a policy, a tolerance, a sign convention, a chart or a rule set. A caller picks
which loop and which period; everything deciding whether an answer is *permitted*
is loaded from the loop's signed bundles. Both gates walk the generated schemas
and fail on a parameter that could carry authority — a convention would last
exactly as long as the next person adding a tool.

**The MCP server is where "the model never writes to the ledger" stops being
prose**, because it is the one interface a model actually drives. It can read,
run a deterministic close, verify, and *propose*. It cannot promote a rule,
attest a decision or widen a tolerance, and there is no parameter through which
to try.

---

---

## 3. What is genuinely valuable

**Not the match rate.** Handed the payout grouping, a trivial exact-amount
matcher (`securo_grouped`) scores 86.4% against our 90.9% — we lead by exactly
one pair, the short-paid payout it cannot match because the amounts disagree.
From P3 until partial payment landed it tied us exactly. That has been the
recorded finding for the whole build and it has not really changed.

**The tail is the product**, and the comparison is stark because a matcher with
no exception model scores zero on all of it by construction:

| | ours | securo_grouped |
|---|---|---|
| exception coverage | **100% (6/6)** | 0% |
| exception classification | **66.7% (4/6)** | 0% |
| ambiguity detection | **100% (1/1)** | 0% |
| false-match rate | 0.00% | 0.00% |

**What a customer actually gets that they cannot get from a matcher:**

1. **Every match carries a proof a third party can re-derive** from the source
   files alone, and a match that fails re-derivation is dropped rather than
   reported. The false-match rate is 0.00% because unverifiable answers never
   reach the number.
   *This was true of the running process and false of the record until
   2026-08-25: the decision log named a `proof_id` and carried no proof, so the
   artifact an auditor is handed cited evidence nobody could fetch. It is true
   of both now — the proof travels in the event, and `POST /v1/verify` is a
   stateless call that needs no account and no database.*
2. **Every unmatched thing has a disposition.** No row leaves a close unaccounted
   for — the run fails rather than finishing quietly over an input nobody named.
3. **Findings a two-way match structurally cannot see.** `E02` is the example: a
   payout billed on the wrong terms still sums to exactly what the bank paid, so
   it reconciles perfectly and the variance walks out the door. We find it by
   noticing the rows disagree with their own population — no contract needed.
4. **A close that replays** — and one that checks itself. The decision log alone
   reproduces the scorecard, and *Re-derive* on the close page re-ingests the
   source files, confirms each sha256 against the hash the record pinned, and
   re-derives every proof. Three failure modes reported apart, because they mean
   different things: different bytes is the reader's mistake, a refutation is our
   finding, and a missing proof is neither and does not pass.
5. **Money that never arrived stays visible.** A partial payment matches *and*
   raises `E04` with the shortfall as a number, rather than absorbing it into
   tolerance or refusing the payout outright.
6. **The authority is signed** and every decision names the bundle that produced
   it.

---

## 4. What is left

**The honest headline until 2026-08-25 was "there is no product surface".** That
is closed. A controller opens a browser, picks a period whose files have
arrived, closes it, works a ranked worklist with the proof expandable per row,
exports the audit bundle, and clicks *Re-derive* to watch the system check
itself against the source files. An external agent gets the same kernel over MCP
and cannot reach anything a human has to sign for.

| | What | Why it matters |
|---|---|---|
| ~~**P15c**~~ | ~~Second loop~~ | **Closed 2026-08-26.** `tds_26as` — Form 26AS from TRACES against a TDS receivable ledger, matched on `TAN + section + quarter` over an April-to-March year. It cost one profile, two adapter specs, a policy, a chart and six taxonomy entries, and **nothing under `engine/`**, which is what turned invariant 7 from an assertion into a measurement. Not GSTR-2B: the point was a loop as unlike settlement as a reconciliation gets, and this one is. |
| — | Cross-close state (`first_seen_at`, `occurrence_count`) | The worklist ranks by the age of the *transaction*, not of the break. `fingerprint` is the precondition, landed, and now survives the record in both directions — two of seven breaks recur across A and B and nothing on the page says so. |
| — | Retention and custody | The journal is *rendered* now — CSV and beancount, and the beancount export is re-loaded by beancount itself, so a third party validates it. What is still missing is durability: it is rendered from `data/runs/`, which is a file anyone with the checkout can delete. A hash chain proves internal consistency, not custody. |
| — | A proposal store | `propose_reclassification` persists nothing, because a proposal outlives the close it speaks about. Said in the response rather than left ambiguous. |
| — | The orders leg | Two of three sources; the third is declared out of scope |
| — | `E05` overpayment | The branch exists, has never executed, and is asserted structurally — the weakest assertion in the codebase |
| — | P12's count | One promoted rule against a gate that says three |

### What building the surface changed about the argument

Worth separating from the feature list. A surface that renders **only what the
decision record says** turned out to be a test of the record, and it found four
things the engine knew and the record could not say — three of them refusals,
which is the class `derive` was built to catch and structurally could not, since
none of them entered the structures the completeness audit walks.

The largest: `MatchProven` carried a `proof_id` and **no proof**. The artifact we
ask a regulator to audit cited evidence nobody could fetch, so the sentence at
the top of §3 — *every match carries a proof a third party can re-derive* — was
true of a live process and false of the record. It is true of both now, and
`test_verification_needs_nothing_but_the_files_and_the_verifier` runs the
re-derivation in a process that imports no server, no close and no benchmark.

### What no amount of further building fixes

Named so it is never mistaken for a to-do list. **Toy scale** — 22 payouts, ~540
rows, two synthetic batches. **One model, one prompt**, and classification
measured at 40–80% across n=5. **Defect rates unvalidated** against real
production formats. **Cost per close is unmeasured** and reported absent rather
than zero. And **every audit behind this design is one person probing their own
work** — including this document.
