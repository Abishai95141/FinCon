# The user flow, and what it is worth

*Written 2026-08-26, after the journal export landed; §5.1 and §5.4 closed
2026-08-27 and are struck through rather than deleted. Every number here came
from running `settlement_3way` against batch A — none of them are estimates.*

The question this answers: **what does a person actually do with this, and what
do they get that they did not have before?**

---

## 1. Who is holding the screen

A financial controller at a company that takes money through a payment gateway
and receives it in a bank account. Mid-market. They close the books monthly, and
between the 3rd and the 8th they have to be able to say one sentence out loud:

> Every rupee a customer paid us in October is either in the bank, or I know
> exactly where it is and why.

If they can say it, they post the journal and the CFO signs. If they cannot, the
auditor finds it, and an auditor's finding is expensive in a way that a week of
their time is not.

## 2. Why the sentence is hard

The gateway settles in **net payouts**. One bank credit of ₹51,990.42 is not one
sale — it is forty transactions, minus the gateway's fee, minus two refunds,
minus a chargeback that landed after the period closed. The bank shows one line.
The order register shows hundreds.

Nobody hand-matches hundreds of orders to twenty-three payouts. So the standard
practice is to match at the payout level, book the fee difference as a plug, and
hope. When it does not tie, someone spends three days in Excel.

Incumbents automate the match and get 85–95%. **They hand back the tail.** The
tail is where the fraud is, where the leakage is, and where the audit finding is
— and it is *the same tail every month*: the same customer with the corrupted
reference, the same gateway netting refunds in a way nobody has written down.

## 3. The flow, with the real numbers

### Sign in → **Data sources**

Two files for the period. Upload them, or load the sample batch. The screen names
what is missing rather than counting it: *"settlement.csv has not arrived"* is
actionable; *"1 source missing"* is not.

### **Close the period**

Six stages, visible while they run, ~1.4s on this batch: ingest · block · match ·
verify · post · record.

**No model runs here.** Not one call, at any stage. Every match is arithmetic
over raw records, and the receipt on the processing page says so, because a
number a controller cannot re-derive is a number they cannot defend.

### The result

```
matched          20 of 23 anchors      87.0%
  by match tier  T0 exact       17
                 T1 tolerant     2
                 T4 declared     1
  by proof tier  P0 arithmetic  19
                 P3 declared     1
```

The decomposition ships with the rate, always. A headline match rate with no
tier split is gameable, and gameable is the same as false here.

**Two denominators, and the difference is not cosmetic.** This screen divides by
the 23 anchors *in scope* — 87.0%, what a controller sees. The benchmark divides
by the 22 anchors that have a true pair at all — **90.9%**, the number in the
README and on the scorecard, because one payout was never banked in the period
and scoring a matcher for missing it would be scoring it against a pair that does
not exist. Both are real, both ship decomposed, and neither is the other.

### **23 journal entries, balanced** — the thing they came for

Double entry, asserted against the bank's own closing figure. Downloadable as
`journal.csv` (RFC 4180, opens in Excel, imports to Tally) or `.beancount`.

Every line carries the proof or exception id it came from, so no figure in the
books is one the controller cannot defend line by line.

**Four exceptions raised no entry, and the pack names all four rather than
omitting them.** Money that never reached the account is a receivable, not cash;
booking it would put a figure in the books the bank does not have.

> This was the actual hole, and it was open until this morning. `post_and_assert`
> rendered the complete ledger, asserted the balance, and *dropped it*. The
> controller could watch the books tie and still had to hand-type every entry.

### **7 exceptions, ₹304,560.53** — the tail, named and priced

| | code | | what the engine says |
|---|---|---|---|
| ₹90,259.47 | `E06` | blocks | group `pout_00011` was claimed by no anchor — re-coded from `E14` by `R-DUP-06`, the first promoted rule |
| ₹87,250.40 | `E09` | blocks | **2 distinct subsets sum to this credit** within tolerance |
| ₹84,769.72 | `E14` | blocks | no strategy matched, and the engine cannot say why |
| ₹39,780.45 | `E14` | blocks | group `pout_00005` was claimed by no anchor |
| ₹1,160.00 | `E14` | blocks | no strategy matched |
| ₹1,050.42 | `E04` | — | reference matched, credit is short — **declared, not absorbed** |
| ₹290.07 | `E02` | — | 12 rows do not follow the relation the other 164 do |

Three of seven are `E14` — *the engine does not know*. That is not a failure of
the write-up, it is the honest measure of how much this system still cannot name,
and saying it out loud beats a plausible guess routed to the wrong desk.

`E09` is the one worth pausing on. Two different subsets of settlement rows sum
to that credit inside tolerance. **There is no correct answer to pick**, and
every tool that returns the first subset it finds is confidently wrong here.
We enumerate, find the ambiguity, and refuse.

### **Work the tail**

Per item: the evidence, the records, and what was tried.

For an `E14`, **Ask the model** sends the facts to `deepseek-v4-flash`, which
must reply through a tool schema — a prose reply is refused and recorded, never
parsed. It comes back with a code, a hypothesis, and a confidence.

**The proposal moves nothing.** Then **Take this item** — you, by name, attest.

### **Sign off**

A named human, a note, and the count of what was still open at signature. The
pack never says "approved" for a close nobody approved.

### **Close pack** — where the artifacts are

One page, everything rebuilt from the record: the seal · the figures · every
source file with its hash and the spec that parsed it · the journal, with both
downloads · the tail · the signed authority · and *"check this without us"*.

---

## 4. What it is worth

**Time.** The 20 provable matches and the 23 entries are free. What is left is
seven items, ranked and priced, instead of a spreadsheet.

**Defensibility.** The auditor is not asked to trust our system. They are handed
a hash-chained log and the source hashes, and `POST /v1/verify` re-derives any
proof from records they ingested themselves. That call needs no account and
touches no state of ours. *"A third party re-derives our answer"* is a property
of the artifact, not a claim about the vendor.

**Compounding — the actual thesis.** A model proposal on this month's break can
be induced into a rule, regression-tested against every historical match, and
promoted. Next month it fires as `P1 RULE` and the item never reaches a human.
`R-DUP-06` already does this. The tail is supposed to *shrink*.

---

## 5. What is missing, stated plainly

Four when this was written on 2026-08-26. **Two closed the same week**, and they
are kept below rather than deleted — a gap that was measured and then closed is
worth more as a record than a gap quietly removed, and 5.1 in particular is the
argument for why the disposition layer exists at all.

### 5.1 ~~"Take this item" leads to no disposition~~ — closed 2026-08-26

Measured, not suspected. Accepting `EXC-00005` from `E14` to `E08`:

```
review log says      : {'EXC-00005': 'E08'}
decision-log code    : E14          <- unchanged
journal entries      : 23 -> 23
journal bytes        : 4994 -> 4994
blocking             : unchanged
```

The attestation is real — hash-chained, named, and it is what unblocks sign-off.
But **the money does not move**. In a real close an exception ends one of four
ways, each producing an entry:

| disposition | the entry |
|---|---|
| **book it** | `E02` fee variance → `Expenses:Gateway:Fees` |
| **carry it forward** | `E01` in-transit → expect it in next month's bank file |
| **chase it** | `E08` missing remittance → a receivable, and someone emails |
| **write it off** | below the materiality threshold, with the threshold named |

That was the state on the morning of 2026-08-26, and the measurement above is
what made it undeniable: the product told you what was wrong, recorded who
agreed, and stopped one step short of the entry that makes the break go away.

**All four exist now**, in `src/recon/disposition.py`, and each one writes double
entry and takes the item off the desk:

| disposition | where the value goes |
|---|---|
| **book it** | the difference is real and explained → an expense |
| **carry it forward** | timing, the money has not landed → cash in transit, an asset |
| **chase it** | somebody owes us → a receivable with an owner and a date |
| **write it off** | value leaving for good → bounded **twice** by the signed policy |

All four are `P2 ATTESTED` and carry a name, which is forced rather than
conventional: value *leaving* a close can never be `P1 RULE`, because raw records
cannot prove a row is spurious — they contain it.

Three things worth keeping from building it.

**`BOOK` is deliberately absent from `DESTINATION`.** The other three name an
account role; booking does not, and supplying a default would let an unratified
code reach an account. A missing key raises where a default would have posted.

**A resolved item did not leave the worklist**, and that needed a fix rather than
copy. An exception is *raised* in the close's record and *ended* in the review
log; the page read the first and never the second, so a person could book, chase
and write off every item and watch the count stay where it was. The good ending
was unreachable and resolving was pointless.

**Mutation found four unguarded controls behind seventeen green tests.** The
ceiling test matched a word the budget message also used; the budget relation
could not see a uniformly-doubled denominator; the accumulation test supplied its
own running total; and the signer test read the route's signature rather than its
behaviour. `make mutate SET=p21` is 14/14 now, and not one of those four would
have been found by reading the tests.

### 5.2 The tail does not persist across closes

`fingerprint` is content-derived, so the same break *is* recognisable next month.
Nothing stores `first_seen_at` or `occurrence_count`. **"This is the fourth month
running"** is the single most valuable sentence a controller can be handed about
a break, and we cannot say it.

### 5.3 The loop called `settlement_3way` matches two legs, not three

```
bank_icici_camt053.xml   side=bank         role=anchor
settlement.csv           side=settlement   role=group
```

`orders.csv` sits in every generated batch and is bound by nothing. The
gateway↔bank tie is done; order register↔gateway is not — and that is precisely
where revenue leakage hides, because a payout can tie to the bank perfectly while
containing an order that was never invoiced.

**The name is a claim the code does not honour.** It should be `settlement_2way`
until the orders leg is bound.

### 5.4 ~~The ledger is not persisted~~ — the export landed; the *durability* did not

The journal is re-derived from the decision log on request rather than stored,
and that remains deliberate: anyone holding the log can produce it, not just the
process that ran the close.

What was missing was that nobody could *get* it. That is closed — the close pack
serves `journal.csv` (RFC 4180, opens in Excel, imports to Tally) and
`journal.beancount`, and the beancount export is **re-loaded by beancount
itself**, so a third party validates the file rather than taking our word that it
balances. Every line carries the proof or exception id it came from.

**The honest remainder is retention, not rendering.** The export is as durable as
`data/runs/`, which is a directory anyone with the checkout can delete. A hash
chain proves internal consistency; it does not prove custody. That is 5.2's
problem in a different costume and neither is solved.
