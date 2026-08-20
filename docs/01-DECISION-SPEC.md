# The Exception Tail — Track 04 decision spec v1

Date: 2026-08-20 · Status: nothing built. This is the thing to approve or reject.
Evidence: [00-RESEARCH-DOSSIER.md](00-RESEARCH-DOSSIER.md)

---

## 1. Problem statement

A controller at a payments-heavy business closes the month by proving three systems agree: what was invoiced, what the gateway settled, what landed in the bank. They never agree. A single payout of ₹4,378.21 represents 87 charges, 4 refunds, 3 chargebacks, 162 fees and an FX adjustment. Gross never equals net. Chargebacks land weeks after the sale. The reference field that would make matching trivial is the field that gets truncated.

**Software already handles the bulk of this.** Trintech publishes 99%+ auto-match rates. NetSuite supports 1:1, N:1 and N:M rules with a confidence-scoring ML assistant. Automated matching hits 90–95% vs 50–60% for spreadsheets.

**So the problem is not the match rate.** Anyone pitching "our AI matches better" is pitching into a solved problem. The honest reframe, from practitioner communities: complaints center *less on whether a tool can match transactions and more on what happens when it can't* — brittle exception queues, and rules that break the moment a new vendor format appears.

Two costs survive automation:

**Cost one — the tail is undifferentiated.** Bank-feed automation cuts a reconciliation from ~47 min to *exception handling only*. The matched records were never the cost. But the 1–10% that fails returns as a flat queue with no reason attached. The controller re-derives context by hand, row by row. Volume fell; cognitive cost per item did not.

**Cost two — the rule treadmill.** Auto-match rates are maintained, not achieved. A new vendor format or fee-schedule change silently degrades matching until someone writes a rule — and rule authoring is gated: *"Some rules are difficult to create... Our IT team typically has to be involved... implementation of new recons & matching rules can be slow."* The rate **decays between engineering cycles**, and the person who understands the exception cannot fix it.

That gap is the product.

---

## 2. Existing solutions, and where each stops

| Category | Examples | Does well | Stops at |
|---|---|---|---|
| Enterprise close | BlackLine, Trintech Cadency | Ultra-high volume, 99%+ auto-match, SOX-grade audit | Exceptions return as a queue. Rule authoring needs IT. Six-figure TCO, phased rollout. |
| ERP-native | NetSuite, SAP, Xero, QuickBooks | 1:1/N:1/N:M rules, ML assistant with confidence scores, sits beside the ledger | Built-in rules can't be edited or reordered. Only as good as inbound reference data. Unmatched lines drop to a manual screen with no explanation. |
| AI-native treasury | Nilus, Trovata, HighRadius | Cash positioning, liquidity agents in CFO-defined rules; 88–92% agentic 13-week forecasts vs 65–75% manual | Optimized for cash *position*, not the transaction-level tail. Rules still human-authored up front. |
| Modern point tools | Numeric, Ledge, bluecopa, Midday | Faster setup, better UX, tiered confidence | Same architecture, nicer surface. Still rule-configured, still hands back a queue. |
| Open source | Beancount/hledger, securo, Firefly III, Actual | Beancount: real double-entry + balance assertions. securo: 892 lines of solid OFX/QIF/CAMT parsing. | securo's reconciler is 142 lines of exact-amount 1:1 greedy — no fee tolerance, no FX, no N:M. Beancount has no matching engine. |
| LLM-first demos | Most of this track | Fast, demos well, handles messy text | 95.6% on lookups → **near 0% on multivariate calculation**. FinBalance: 26–41pp gap between reported results and replaying the models' own entries. Wrong, coherently, silently. |

**The gap nobody occupies:** a system where resolving an exception *is* how the rule gets written, and where the machine cannot book a match it can't prove.

---

## 3. Solution

Three mechanisms, in dependency order.

### 3.1 Proof-carrying matches
Deterministic engine decides every match across four tiers — T0 exact, T1 tolerant, T2 subset-sum (the N:1 settlement case), T3 unmatched. Each accepted match emits a **proof object**: record IDs both sides, arithmetic closing to zero, tolerance consumed, rule that fired, resulting journal entry.

```
match M-0412  tier T2 subset-sum  rule R-017@v3
  payout   BANK/2026-08-14/CR    +4,378.21
  charges  87 × settlement rows  +4,612.90
  refunds   4 × settlement rows    -118.40
  fees    162 × settlement rows    -114.02
  fx adj    1 × settlement row       -2.27
  ────────────────────────────────────────
  residual                          0.00   tolerance used 0.00 / 0.50
  verdict  PROVEN
```

A match without a passing proof is not a match. This is what makes a reported match rate trustworthy — and what makes it safe to let a model near the pipeline at all.

### 3.2 Explained, ranked exceptions
Everything unmatched goes to the model: classified into a fixed 12-code taxonomy (`E01`–`E12`), with hypothesis, cited evidence, suggested resolution, ranked by cash impact × age. A worklist, not a queue.

`E09` (netting ambiguity) matters most: when several invoice subsets sum to the same payout, **there is no unique correct answer**. A system that picks one is fabricating. Escalating ambiguity is a correctness feature — and the case every LLM-first demo will silently guess.

### 3.3 Rule induction — the compounding loop
When the controller resolves an exception, the model proposes a deterministic rule that would have prevented it. Shown as a diff and **regression-tested against every historical match before promotion**: how many existing matches break, how many past exceptions now auto-clear. Controller approves; rule enters the engine, versioned.

This inverts how agent products age: the system becomes **more deterministic over time, not more agentic**. It also removes the IT gate.

---

## 4. User flow

| # | Step | Actor |
|---|---|---|
| 01 | Drop three sources — invoice register, gateway settlement, bank statement (CAMT.053/OFX/CSV) | Human |
| 02 | Ingest + normalize — canonical record, Decimal never float, `doc_hash` for idempotent re-ingest | Engine |
| 03 | Read messy fields — memos, remittance PDFs → structured proposals (PageIndex for long docs) | Model |
| 04 | Block, then match — candidates by amount/date/reference, then T0→T1→T2, each emitting a proof | Engine |
| 05 | Read the scorecard — matched X of Y, false-match rate, N exceptions, unreconciled value | Human |
| 06 | Triage the tail — `E01`–`E12`, hypothesis, evidence, rank by cash impact | Model |
| 07 | Resolve one exception — one decision, in context, evidence pre-assembled | Human |
| **08** | **Rule proposed + regression-tested** — "0 matches broken · 14 exceptions would auto-clear" | Model + Engine |
| **09** | **Approve the rule** — qm `NeedsApproval` gate; versioned on approval | Human |
| 10 | Post + assert — journal entries written, balance assertion vs bank closing balance. **Doesn't balance → close is blocked**, not warned | Engine |
| 11 | Next cycle measurably better — scorecard attributes the lift rule by rule | Engine |

Steps 08–09 are the loop. Everything else is table stakes; that pair is the product.

---

## 5. What we ship

| Artifact | What it is |
|---|---|
| Synthetic generator | Plants known exceptions at known rates; complete labels by construction. Shipped so numbers are reproducible. |
| Match engine | T0–T3, tolerance model, bounded subset-sum with ambiguity detection. The differentiated core. |
| Proof verifier | Independent checker; re-derives every match from raw records. Fails re-derivation → rejected, not reported. |
| Double-entry ledger | Beancount-shaped, balance assertions gate the close. |
| Agent edge | Normalizer, triage, rule induction. Three jobs, no others. |
| Eval harness | Four ablation arms, eight metrics, adversarial held-out set. |
| Scorecard + worklist UI | The two screens a controller uses. Proof expandable on every row. |
| Audit export | Every decision with proof, rule version, approver. |

### The demo, in ninety seconds
1. Run close on batch A → scorecard, **false-match rate 0.00%**, 11 ranked exceptions.
2. Resolve three. Approve three induced rules, each showing "0 broken, N would auto-clear."
3. Run close on batch B — **fresh data never seen**. Auto-match measurably higher, lift attributed rule by rule.
4. Show the LLM-only ablation arm: higher naive match rate, non-zero silent false matches. Then ours rejecting those same matches for failing their proofs.

Step 3 is the differentiator. A **measurable learning curve on held-out data** is the only honest way to show the agent added value rather than narrated.

---

## 6. Impact

Claims we can substantiate in our own harness, not vendor arithmetic.

- **Target false-match rate 0.00%** — structurally enforced by the proof gate
- **Auto-match lift on held-out data** after N human resolutions — the measurable learning curve
- **Zero IT tickets** to author a new matching rule
- **12 exception codes** — fixed vocabulary, not prose

What changes for the controller:
- Exception cost per item falls — context arrives assembled instead of re-derived per row
- The tail shrinks permanently — resolving one exception clears its whole class
- The rule treadmill stops — auto-match stops decaying between engineering cycles
- The audit trail is machine-checkable, not merely present

**What we are NOT claiming:** not a higher match rate than BlackLine/Trintech (they're at 99%+, we won't beat that); no hours-saved figures (no production deployment to measure); not enterprise-ready. We should refuse to make any claim the harness can't substantiate.

---

## 7. Trade-offs

### Where we lose
- **Headline match rate.** A guessing model reports a higher number than an engine refusing unproven matches. We look worse on the vanity metric and must argue the point.
- **Recall ceiling from blocking.** A true pair dropped at candidate generation can never be matched. We measure blocking recall; we can't remove the ceiling.
- **Large-N subset-sum.** Bounded search to stay tractable, so some legitimate very-large-N matches fall to exceptions.
- **Build cost.** A deterministic engine plus proof verifier is far more engineering than a prompt. Most of the window goes here before any agent exists.
- **Enterprise scale/compliance.** No SOX controls, no multi-entity consolidation, no millions-of-rows throughput.

### Where we win
- **False-match rate** — structurally near-zero; this is the error that corrupts books
- **Exception quality** — classified, evidenced, ranked
- **Rule authoring without engineering**
- **Ambiguity honesty** — `E09` escalates instead of guessing
- **Reproducibility** — replay plus a shipped generator; a skeptic can re-run every number

### Risks carried

| Risk | Mitigation | Residual |
|---|---|---|
| Induced rules overfit, create false matches later | Regression gate vs full match history; rules versioned and revocable | A rule can be right on history and wrong on future data. Needs monitoring, not just a gate. |
| Synthetic eval ≠ real data | Adversarial held-out set; generator shipped for inspection | **Real.** Our numbers describe our generator. Say so plainly. |
| Two languages (Python engine, TS harness) | Clean HTTP seam; engine as a service | Integration cost in a short window; may force harvesting qm patterns over adopting core. |
| Engine-before-agent means late demo risk | Build order puts a number on the board at step 3 of 9 | If T2 overruns, ship T0/T1 + the full loop and say so. |
| Model still does extraction (~88% accurate) | Extraction outputs are proposals; proof gate catches downstream errors | A misread field causes a *missed* match (safe), not a false one (unsafe). Asymmetry is intentional. |

---

## 8. What it looks like when it's done

A controller drops three files and runs one command. Ninety seconds later: a scorecard, a double-entry ledger that balances or explicitly refuses to, and eleven exceptions — each with a code, a hypothesis, the evidence, and a rupee figure. They work the top three; each resolution produces a rule the system tests against its own history before asking permission to keep.

Next month the same three files produce eight exceptions instead of eleven, and the scorecard says which rules earned the difference.

Nothing in the ledger was written by a language model. Everything the model touched was a proposal a deterministic engine either proved or refused.

**One-line pitch:** incumbents automated the match and handed back the tail. We automate the tail — and make every resolution permanent.

---

## 9. Decisions still open

| Decision | Options | Lean |
|---|---|---|
| Ledger substrate | Embed Beancount · mirror schema in Postgres | Beancount — balance assertions come free and are the close gate |
| Primary loop | Gateway settlement · GSTR-2B ITC matching | Settlement — forces N:M, where the differentiation lives |
| qm adoption depth | Full harness · harvest patterns | Harvest approval-gate + audit + replay; full adoption only if time allows |
| Language | Two-language with HTTP seam · single-language reimplementation | Two-language — Beancount and Splink are worth the seam |

---

## Sources new to this document

[Trintech — transaction matching](https://www.trintech.com/cadency/match/) · [BlackLine — transaction matching](https://www.blackline.com/products/financial-close/transaction-matching/) · [Houseblend — NetSuite auto-match rules & workflows](https://www.houseblend.io/articles/netsuite-bank-reconciliation-auto-match-rules) · [Oracle — matching bank data](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_4843222719.html) · [Numeric — reconciliation automation: strategy, ROI, implementation](https://www.numeric.io/blog/reconciliation-automation) · [Nilus — AI-native treasury platforms 2026](https://www.nilus.com/blog/the-7-best-ai-native-treasury-platforms-in-2026-honest-buyers-guide/) · [Nilus — agentic AI for treasury](https://www.nilus.com/blog/what-is-agentic-ai-for-treasury-a-2026-definitive-guide/) · [bluecopa — transaction matching software 2026](https://www.bluecopa.com/blog/transaction-matching-softwares) · [Rexi — changing reconciliation rules without engineering](https://rexi.finance/blog/payment-reconciliation-software/changing-reconciliation-rules-without-engineering.html)

Everything else is sourced in [00-RESEARCH-DOSSIER.md](00-RESEARCH-DOSSIER.md).
