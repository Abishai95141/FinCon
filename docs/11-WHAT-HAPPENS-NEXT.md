# What happens after "reconciled"

*Written 2026-08-26. Three questions answered: how many documents this engine can
reconcile, what practitioners expect a reconciliation tool to do once it has
matched, and the one flow we should build.*

Sources are listed at the end. Reddit blocks our crawler, so the practitioner
voice here comes from accounting-forum content, vendor documentation aimed at
controllers, and India-specific settlement guides — not from r/Accounting.

---

## 1. How many documents can this reconcile?

**Two sides. Any number of files.**

```python
class LoadedSources:
    anchor_rows: list[tuple[str, Record]]
    group_rows:  list[tuple[str, Record]]
```

That is the whole shape. `Offer` — what every strategy receives — is *one anchor
and the groups still available*. `T0`, `T1`, `T2` and `T4` are all anchor ↔
group. There is no third bucket anywhere in `engine/`.

**Files are not the limit.** `Loop.sources` is `tuple[SourceBinding, ...]` of any
length and each binding names its own `role`. Three bank statements as anchors
and two settlement exports as groups is five files and works today. What does
*not* work is a third **side** — a leg that must agree with the other two rather
than with one of them.

### The two ways to get a real three-way, and which to build

**(a) Chained pivot.** Orders ↔ gateway in one pass, gateway ↔ bank in another,
with the gateway leg as the pivot that appears in both. Two 2-way matches
sharing a middle.

**(b) True simultaneous N-way.** One anchor, N group sides, residual closing
across all of them at once.

**Build (a).** Three reasons, in order of weight:

1. **It is what the domain already does.** The standard description of settlement
   reconciliation is explicitly two-pass: match `settlement_id` to the bank
   UTR + date + net amount, *then* explode the batch by `order_id` and
   `payment_id`. Practitioners do not reconcile three things at once; they
   reconcile a chain.
2. **`E09` would become unusable under (b).** Subset-sum ambiguity across two
   sides already produces "two distinct subsets sum to this credit". Across
   three sides it is subsets of subsets, and the honest answer becomes *ambiguous*
   so often that the code stops carrying information.
3. **Nothing in `engine/` has to change.** A second pass is a second
   anchor/group pair. Invariant 7 holds — the engine stays domain-agnostic and
   the chaining lives in the profile.

This is not a weaker claim. In accounting, "three-way match" *means* two matched
pairs sharing a pivot — that is how a PO/GRN/invoice match works too.

**And the name must change now, either way.** The loop registered as
`settlement_3way` binds exactly two files. `orders.csv` is generated into every
batch and bound by nothing. Until the orders pass exists, the honest name is
`settlement_2way`.

### What the third leg actually buys

A payout can tie to the bank perfectly and still be wrong. The bank says
₹51,990.42 arrived; the gateway says that payout contains order `ORD-8842`; the
order register has never heard of `ORD-8842`. Both existing legs agree. Nothing
in a 2-way close can see it.

That is the class of finding worth having, and it needs `orders.csv` bound.

---

## 2. What practitioners expect after the match

Four things, and we do two and a half of them — 2.1 closed on 2026-08-26 and is
struck through below rather than deleted.

### 2.1 A disposition, not a label

The consistent shape across every source: a reconciling item is investigated,
then **an adjusting journal entry is prepared**. "For each identified
discrepancy, prepare appropriate adjusting journal entries to correct the
accounting records."

Timing differences are the exception that proves it — they are **tracked as
reconciling items** rather than corrected, because they will clear themselves.
Everything else ends in an entry.

~~We produce the label, the evidence and the attestation, and no entry.~~
**Closed 2026-08-26.** All four dispositions exist in `src/recon/disposition.py`
and each writes double entry. [10-THE-USER-FLOW.md](10-THE-USER-FLOW.md) §5.1
keeps the measurement that made the gap undeniable, because a gap that was
measured and then closed is worth more as a record than one quietly removed.

### 2.2 Ageing — the thing we cannot say at all

Reconciling items are bucketed **0–30 / 31–60 / 60+ days**. An item over 30 days
is a red flag that needs a written explanation in the workpaper; the target is
**zero items open beyond 60 days**; ageing is what drives an item to write-off
rather than resolution.

We have no ageing whatsoever. `fingerprint` makes a break *recognisable* across
closes and nothing records when it was first seen. "This is the fourth month
running, and it is now 94 days old" is the single most useful sentence about a
break, and we cannot produce it.

### 2.3 Preparer ≠ reviewer

> The person who prepares the reconciliation should never be the same person who
> approves it.

This is segregation of duties and it is a primary internal control, not a nicety.
**Our sign-off is one button pressed by whoever happened to work the tail.** The
same account that accepts every classification can then sign the close. That is
a genuine control gap in a product whose entire pitch is verification, and it is
cheap to fix: two roles, and a close that will not seal until the reviewer is
someone other than the preparer.

### 2.4 A suspense account

The standard accounting home for an unresolved reconciling item is a **suspense
account**, monitored by open-line count and the age of the oldest open line —
and cleared before the close. We have `Liabilities:UnappliedCash` in the chart
and nothing routes to it as a suspense destination.

---

## 3. India: a code we do not have

Indian gateway settlements embed **multi-tier deductions** — MDR, **GST on MDR
at 18% (ITC-eligible)**, TCS, and **§194-O TDS at 1%** on e-commerce seller
payments, verified against Form 26AS. The industry variance vocabulary is:

| theirs | ours |
|---|---|
| `FEE_DEDUCTION` | `E02` fee variance |
| `ROUNDING` | `E03` FX / rounding |
| `PARTIAL_PAYMENT` | `E04` partial payment |
| `UNEXPLAINED` | `E14` unexplained |
| **`TAX_DEDUCTION`** | **nothing** |

A TDS or GST deduction currently lands in `E02` (a fee variance) or `E14`
(unexplained). Both are wrong, and the second is worse than it looks: TDS
reconciles against a *government* record, not against a contract, so it is a
different investigation routed to a different desk.

The registry has been open since P11 precisely for this. `X-TAX-DEDUCTION`
should be minted, and it should stay `PROVISIONAL` until someone writes the
definition — naming grants nothing.

**Also worth stating plainly:** the benchmark quoted to Indian finance teams is
moving from ~51% (manual VLOOKUP) to **88% or above**. We are at **87.0%** on
the controller-facing denominator — 20 of 23 anchors in scope — and 90.9% on the
benchmark's, which divides by the 22 anchors that have a true pair. The
conservative one is the fair comparison here, so we are at the line, not past
it.

---

## 4. What a controller expects to leave with

| artifact | we have it |
|---|---|
| Journal entries to post | **yes** — `journal.csv`, `.beancount`, since 2026-08-26 |
| Order-level revenue posting | no — needs the orders leg |
| MDR expense with GST split out for ITC | no — needs `X-TAX-DEDUCTION` |
| Refunds tied to their original orders | no — needs the orders leg |
| An **exception ledger** of unexplained lines | partly — the tail is on the pack, not exported |
| Entries posted **into the ERP**, not exported | no — this is the incumbent differentiator |
| Workpaper with sign-offs | yes — the close pack |
| Carry-forward file for next period | **no** |

The month-end sign-off that Indian practice expects should document: the date of
the final bank reconciliation, the outstanding exception count **and its
materiality classification**, TDS mismatches pending correction, ITC reversals,
**platform settlement variances carried forward**, and the name **and
designation** of the approving authority.

We produce the date, the count, and the name. We do not produce materiality
classification, TDS, ITC, carry-forward, or designation.

---

## 5. The flow to build

No options. This is the flow.

```
1  LOAD       the period's files                          exists
2  CLOSE      deterministic: match, prove, post           exists
3  TRIAGE     every unmatched item gets a code + owner    exists
4  DECIDE     one of four dispositions, each an entry     exists (2026-08-26)
5  SIGN       preparer signs, reviewer approves           half exists
6  HAND OFF   journal + pack + carry-forward              two of three
7  NEXT CLOSE carried items return, with an age           does not exist
```

### Step 4 — the four dispositions

**Built 2026-08-26**, as specified below and with the bounds intact. Each one
produces a journal entry. Each one closes the exception. Nothing else does.

| | when | the entry | tier |
|---|---|---|---|
| **Book** | the difference is real and explained | Dr the named expense · Cr Clearing | `P1` if a promoted rule fires, else `P2` |
| **Carry forward** | timing — the T+1..T+3 lag, `E01` | Dr Cash-in-transit · Cr Clearing, and it **reopens next period** | `P2` |
| **Chase** | money owed to us, `E08` | Dr Receivable · Cr Clearing, with an owner and a due date | `P2` |
| **Write off** | aged out, or under the policy's materiality floor | Dr Write-off · Cr Clearing | `P2`, and the floor comes from **policy** |

**Every one is `P2 ATTESTED` or better, and none is `P1 RULE` by default.** Value
leaving a close cannot be proven from raw records — the records *contain* the
row; they cannot show it is spurious. A rule may propose a disposition; only a
human may make one.

**The threshold is not the clicker's to choose.** A write-off floor supplied by
the person doing the writing off is audit finding `F2` wearing a new hat. It
comes from the signed policy bundle, and the close pack prints it.

### Step 7 — ageing

A carried-forward item gets `first_seen_at` and `occurrence_count` on its
fingerprint. Next close it returns with an age, and the buckets are the ones the
profession already uses:

- **0–30 days** — normal
- **31–60 days** — the pack demands a written explanation
- **60+ days** — the pack flags it, and the reviewer sees it before signing

### The two control changes that come with it

1. **Preparer ≠ reviewer.** Two roles. A close does not seal while the person
   approving it is the person who worked the tail.
2. **A disposition budget.** Rule 1's `F4` finding again: a reason makes a
   write-off legible, a *budget* makes it bounded. If 40% of the tail's value
   leaves through write-off, the close says so before it seals.

---

## 6. Order of work

1. **Rename `settlement_3way` → `settlement_2way`.** One line, and it stops the
   file map lying. Do it before anything else.
2. ~~**The four dispositions**, with entries, on the existing 2-way loop.~~
   **Done 2026-08-26** — `src/recon/disposition.py`, four endings, both
   write-off bounds from policy, `make mutate SET=p21` 14/14.
3. **Ageing** — `first_seen_at`, `occurrence_count`, and the three buckets on
   the pack.
4. **Preparer ≠ reviewer.**
5. **The orders leg**, as a chained second pass — restoring the `3way` name
   honestly.
6. **`X-TAX-DEDUCTION`**, provisional, once someone writes the definition.

---

## Sources

- [Numeric — Month-end reconciliation](https://www.numeric.io/blog/month-end-reconciliation) — the five-step workflow, adjusting entries, the 60-day target, preparer/reviewer as internal control
- [Hyperbots — Reconciliation aging](https://www.hyperbots.com/glossary/reconciliation-aging) — the 0–30 / 31–60 / 60+ buckets
- [Numeric — Balance sheet reconciliation](https://www.numeric.io/blog/balance-sheet-reconciliation) — items over 30 days as a workpaper red flag
- [HighRadius — Segregation of duties](https://www.highradius.com/resources/Blog/segregation-of-duties-accounts-payable/) — preparer must not be approver
- [SolveXia — Suspense accounts](https://www.solvexia.com/blog/suspense-account) and [Phacet — Clearing suspense before the close](https://www.phacetlabs.com/blog/clear-suspense-account) — open-line count, age of oldest line, ageing drives write-off
- [Terra Insight — Razorpay settlement reconciliation](https://www.terra-insight.com/insights/razorpay-settlement-reconciliation/) — net payouts, two-pass matching, the variance vocabulary, the 51% → 88% benchmark
- [OneFinOps — Razorpay for finance teams](https://onefinops.com/glossary/razorpay) and [Terra Insight — Reconciliation FAQs India](https://www.terra-insight.com/faqs/) — MDR, GST on MDR, TCS, §194-O TDS, Form 26AS, the sign-off checklist
- [Numeric — Account reconciliation software](https://www.numeric.io/blog/account-reconciliation-software) — journal entries posting directly to the ERP as the incumbent differentiator
