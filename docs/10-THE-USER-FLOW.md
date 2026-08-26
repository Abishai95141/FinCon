# The user flow, and what it is worth

*Written 2026-08-26, after the journal export landed. Every number here came from
running `settlement_3way` against batch A — none of them are estimates.*

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
| ₹90,259.47 | `E14` | blocks | group `pout_00011` was claimed by no anchor |
| ₹87,250.40 | `E09` | blocks | **2 distinct subsets sum to this credit** within tolerance |
| ₹84,769.72 | `E14` | blocks | no strategy matched, and the engine cannot say why |
| ₹39,780.45 | `E14` | blocks | group `pout_00005` was claimed by no anchor |
| ₹1,160.00 | `E14` | blocks | no strategy matched |
| ₹1,050.42 | `E04` | — | reference matched, credit is short — **declared, not absorbed** |
| ₹290.07 | `E02` | — | 12 rows do not follow the relation the other 164 do |

Four of seven are `E14` — *the engine does not know*. That is not a failure of
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

Four things, and the first one is large.

### 5.1 "Take this item" leads to no disposition

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

None of the four exist. Today the product tells you what is wrong and records
who agreed — and stops one step short of the entry that makes the break go away.
**That is half a product**, and it is the next thing to build.

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

### 5.4 The ledger is not persisted

The journal is re-derived from the decision log on request rather than stored.
That is the stronger construction — anyone holding the log can produce it, not
just the process that ran the close — but there is no ledger file, and a pack
implying otherwise would claim a durability this build does not have.
