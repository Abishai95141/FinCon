# STATUS — progress tracker

**Read [CLAUDE.md](CLAUDE.md) first.** This file is the live state of the build. Update it every session, at the end of the session, with real command output.

| | |
|---|---|
| **Current phase** | `P4` — blocking + Splink, blocking recall on the scorecard |
| **Last green gate** | **P3** — 24/24. `make verify` runs P0–P3, 73 tests. |
| **Build runs?** | Generator, ledger, intake and the T0/T1 engine do. |
| **Last verified numbers** | batch A/B: deterministic **90.9% auto-match, 0.00% false-match**, precision 100% |
| **Updated** | 2026-08-20 |

---

## How to update this file

A gate is **green only when the command output that proves it is pasted below.** Not "looks right", not "should work" — the output. A gate with no output is `not started`, whatever the code looks like.

Status values: `not started` · `in progress` · `RED` (attempted, failing) · `GREEN` (output pasted below).

`RED` is a legitimate, useful state. Leaving a gate red with an honest note is correct. Marking it green without the output is the one thing that breaks this document — see CLAUDE.md rule 1.

---

## Phase gates

| Phase | Gate | Status | Evidence |
|---|---|---|---|
| **P0** | Generator emits batch A and B with complete labels; adversarial cases present; a second person can regenerate identical batches from a seed | **`GREEN`** | [below](#p0--generator--ground-truth--2026-08-20) |
| **P1** | Round-trip a hand-built journal through Beancount; an unbalanced entry is *rejected*; a wrong closing balance *blocks* the close | **`GREEN`** | [below](#p1--contracts--ledger--2026-08-20) |
| **P2** | Both hand-written specs (CAMT, Shopify) ingest cleanly; a deliberately corrupted spec is caught by roll-forward, not inspection | **`GREEN`** | [below](#p2--intake--2026-08-20) |
| **P3** ◆ | **First number.** Auto-match rate + false-match rate, ours vs securo baseline, on batch A | **`GREEN`** | [below](#p3--first-number--2026-08-20) |
| **P4** | Blocking recall measured against A's labels and printed on the scorecard | `not started` | — |
| **P5** | Planted ambiguous payout raises `E09`; solver timeouts surface as `E13`, never as silent non-matches | `not started` | — |
| **P6** ◆ | `make eval` produces the full 4-arm × 8-metric comparison on A and B from a clean checkout | `not started` | — |
| — | **◆ MINIMUM SHIPPABLE LINE** — everything below is upside | | |
| **P7** ◆ | **The lift number.** Resolve 3 on A, approve 3 rules, re-run on held-out B, scorecard attributes improvement rule by rule | `not started` | — |
| **P8** | An external process calls `run_match` and re-derives the returned proof without touching our database | `not started` | — |
| **P9** | A controller completes one close through the UI without a terminal | `not started` | — |
| **P10** | A second loop (GSTR-2B) closes with zero kernel code changed — profile and adapters only | `not started` | — |

◆ = the three gates that carry the claim. **P7 is not cuttable.**

---

## Evidence log

Paste gate output here as gates go green. Newest at the top. Keep the command, not just the result.

<!-- template:
### P3 — first number · 2026-MM-DD
```
$ make gate P=3
...actual output...
```
Notes: anything surprising, anything still weak.
-->

### P3 — first number · 2026-08-20

```
$ .venv/bin/python -m bench.run --batch A
batch A  ·  22 gateway credits  ·  517 settlement rows
true pairs (payouts banked in period): 22

arm               auto-match  false-match  precision   recall  correct  false  missed
-------------------------------------------------------------------------------------
securo_raw             0.0%       0.00%      0.0%    0.0%        0      0      22
securo_grouped        90.9%       0.00%    100.0%   90.9%       20      0       2
deterministic         90.9%       0.00%    100.0%   90.9%       20      0       2
  securo_raw: securo's 1:1 exact-amount matcher on raw rows
  securo_raw: applied outside its designed domain (it pairs internal transfers, not N:1 settlements) — a low score here is expected and is the point
  securo_grouped: securo's rule, given the payout grouping for free
  securo_grouped: the fairer comparison: it isolates the matching rule from the grouping, which is most of the work
  deterministic: tiers: {'T0': 18, 'T1': 2}
  deterministic: 8 record(s) the source left ungrouped — unreachable by T0/T1, deferred to subset-sum at P5
```

Batch B is identical to two decimal places. `make verify` runs P0–P3, 73 tests.

**The finding that matters, and it does not flatter us.** Once securo's rule is
handed the payout grouping it produces *pairs identical to ours* — `ours.pairs
== theirs.pairs` is asserted, not observed in passing. Our T0/T1 matching rule
contributes **nothing** over a 1:1 exact-amount matcher on this batch. The
grouping is most of the work, and the tail is where the difference lives. That
is exactly what the decision spec argued from Trintech's published numbers; this
is the same conclusion from our own data.

`securo_raw` at 0% is its algorithm on rows as they actually arrive — a 1:1
exact matcher cannot address an N:1 problem. True, but on its own it is not a
fair comparison, which is why `securo_grouped` exists and why the arm carries
its caveat in `notes` beside the number rather than in a footnote.

**Both arms miss exactly two payouts, and missing them is correct**: the E06
duplicate (bank paid the right amount, the export double-counted, so the
residual is far past tolerance) and the E09 ambiguous payout. 90.9% is therefore
the *ceiling* at T0/T1, not a shortfall — nothing else on this batch is
matchable without subset-sum.

**Mutation-tested.** Replacing `verify()` with an unconditional `PROVEN` — the
exact rubber stamp CLAUDE.md rule 1 names — fails **7 of 24** tests. A 0%
false-match rate is worth nothing if the verifier stamps whatever it is handed,
so every way a proof can lie is asserted to be refuted: inflated leg subtotal,
residual that does not follow from the records, a record counted in two legs, a
reference to a record that does not exist, a leg holding another side's records,
and a caller-supplied sign convention the proof cannot choose for itself.

**Three bugs found.**
1. *The T1 truncation was a no-op.* The generator truncated payout references
   with `[:12]` on a 10-char id, so **zero** truncated-reference cases existed
   and the tolerant tier had nothing to exercise it — it would have passed as
   dead code. Now truncates to 8 chars, and the labels record which payouts.
   T1 fires on exactly those two, asserted by id rather than by count.
2. *Match keys were not comparable across sources.* A bank narration yields
   `RAZORPAY`, a settlement column yields `razorpay`, so every T1 candidate was
   filtered out and T1 matched nothing. Keys are now casefolded on write in the
   interpreter — keys exist to be compared, so comparability is a property of
   the destination rather than something every consumer must remember. Case is
   preserved in `raw`, which is evidence and never matched on.
3. *I had handicapped the baseline.* `securo_grouped` represented each payout by
   its **earliest** row, putting the delta 3 days from the bank credit and
   outside securo's ±2 window — scoring it zero for a reason of our choosing.
   A payout settles *after* its charges, so the latest row is the fair
   representative. Changed, and the baseline went 0% → 90.9%.

**P0 evidence refreshed.** The truncation fix changes batch bytes, so the
committed hashes moved. Regenerated, P0 re-run green, new manifest below.

```
  A/bank_camt    fee9a06bdcdbf91f      B/bank_camt    81f1b1d5727c8a75
  A/bank_csv     73f598ad8e8fd1fa      B/bank_csv     bb857bb69cc2f564
  A/labels       2e95cf3ce938388b      B/labels       de18ca6e6c9bfed7
  A/orders       cbbf6d4b5b7a10ee      B/orders       cbe3d63cb2c6b703
  A/settlement   71d7a9bc1bb5724c      B/settlement   42f1ccddfbe3b367
```

---

### P2 — intake · 2026-08-20

```
$ make verify
=== gate P0 ===   11 passed      === gate P1 ===   19 passed
=== gate P2 ===   19 passed

$ .venv/bin/python -m pytest -q      49 passed in 0.26s
$ make lint                          All checks passed! · 51 files formatted

  icici-current      [verified] 26/28 parsed, 2 rejected :: roll_forward=pass control_total=skip
                                                            idempotence=pass row_conservation=pass type_domain=pass
  icici-camt         [verified] 26/26 parsed, 0 rejected :: roll_forward=pass ...
  shopify-orders     [declared] 250/250 parsed          :: roll_forward=skip control_total=skip ...
  gateway-settlement [declared] 517/517 parsed          :: roll_forward=skip control_total=skip ...
```

Four hand-written specs, no model involved. Two sources carry balances and come
back **verified**; two carry none and come back **declared** — the honest
degradation from the addendum, with `provenance` capped at `P3` for the latter.

**The gate's core claim, demonstrated.** Point the credit amount at the
`Closing Balance` column — a plausible mistake, both columns are money, both
parse, and the corrupted spec produces *exactly as many records as the good one*
(the test asserts that, so it cannot be caught trivially). Nothing about the
output looks wrong. Roll-forward catches it and localises it:

```
row 2: 680108.64 + 709646.38 = 1389755.02, but the source states 709646.38
       (delta 680108.64)
```

**A hole found while testing the second corruption.** A spec with a wrong date
format parsed **zero** rows and still reported `declared`. Every check passed or
skipped vacuously: row conservation balanced (0 parsed + 28 rejected = 28),
roll-forward skipped for want of records, type-domain passed over an empty set.
But "declared" means *we got data we could not fully verify* — getting nothing
is a different thing and must not borrow that label. Row conservation now fails
when a document has rows and none survive, and reports the first rejection
reason. That corruption is now `failed`, not `declared`.

**Contract bumped 1.0.0 → 1.1.0.** `FieldMap.sign` added so split Dr/Cr exports
can map two columns onto one amount. A new optional field is a *minor* bump per
the rules in `contracts/__init__.py`, and the changelog is in that file. The
validator rejects `sign` on any verb other than `DECIMAL`, where it would be a
silent no-op.

**Cross-format agreement.** The CSV and the CAMT.053 describe the same account;
movements tie at ₹274,577.56 across both, with equal record counts. Neither file
alone would reveal a spec error in the other.

**ADR-001 asserted structurally, not just documented.** A test walks the AST of
every file under `src/recon/intake/` and fails on any `eval` / `exec` / `compile`
/ `__import__` call or `.system` / `.popen` attribute. The parse registry is also
asserted complete at *import* time, so a `ParseVerb` member added without an
implementation breaks the build rather than surfacing on a customer's file.

**P0 evidence re-checked** after ruff reformatted `proofs.py` and friends:
`MANIFEST.json` regenerated and diffed against the commit — unchanged.

**Not built:** XLSX, OFX and QIF readers raise `ReaderError` rather than
returning an empty document. `control_total` has no source that states one yet,
so it only ever SKIPs — it is untested against a real tie-out.

---

### P1 — contracts + ledger · 2026-08-20

```
$ make verify
=== gate P0 ===   11 passed in 0.09s
=== gate P1 ===   19 passed in 0.10s

$ .venv/bin/python -m pytest -q
30 passed in 0.19s

$ make lint
All checks passed!    48 files already formatted
```

The three gate behaviours, verified against the real beancount 3.2.3 loader
rather than our own idea of what should balance:

| | verdict | beancount error |
|---|---|---|
| balanced journal + correct closing balance | proceeds, 1 txn loaded, `entry_id`/`proof_id` survive the round trip | — |
| entry whose postings sum to ₹10.00 | **blocked** | `ValidationError` |
| closing balance asserted at ₹999,999.00 | **blocked** | `BalanceError` |

**Balance-assertion date offset is load-bearing, and the gate proves it.**
Beancount evaluates a `balance` directive at the *start* of its date, so an
assertion dated `period_end` cannot see that day's postings. `assert_closing_balance`
dates it `period_end + 1`. The test posts an entry **on** period_end and asserts
that the naive same-day form *fails* — if someone removes the offset, that test
goes red instead of the bug shipping silently.

**Two bugs found and fixed during the build.**
1. Journal metadata rendered with Python `!r` produced `'M-0001'` — single
   quotes — and beancount's lexer rejected it. Only visible because the ledger
   is round-tripped through the real loader; a self-written "does this look like
   valid beancount" check would have passed it.
2. `tests/gates/` collected **zero tests** on directory collection: pytest globs
   `test_*.py`, and the gate files are `gate_p*.py`. `make gate P=N` passes an
   explicit path so P0 was genuinely verified, but `make test` was silently
   skipping every gate. Fixed via `python_files` in pyproject; `make test` now
   includes `tests/gates`.

Contract validators are tested for *refusal*, not just construction — a contract
whose validators accept everything is documentation. Enforced and covered:
money rejects `float` outright; `Record` is frozen and currency must be ISO-4217;
a `P1` proof must name its rule, `P2` its attester, `P3` its gap; `E09` must
carry ≥2 disjoint alternatives; a `Rule` cannot reach `PROMOTED` while its
regression report shows a broken historical match (CLAUDE.md invariant 5, made
unrepresentable rather than merely policy); `SUPPRESS` must state a reason;
`AdapterSpec` rejects a verb outside the closed enum, an unbounded regex, and
any spec that cannot produce a Record.

**Ruff reformatted `emit.py` during this phase.** Since `MANIFEST.json` is P0's
committed evidence, the manifest was regenerated and diffed against the commit:
unchanged. P0's evidence still holds.

**Not built:** nothing consumes these contracts yet. `Record` has no producer
until P2, `Proof` no producer until P3, `Rule` no interpreter until P7. The
contracts are frozen at `1.0.0` from here — see ADR-002 for what a change costs.

---

### P0 — generator + ground truth · 2026-08-20

```
$ make verify
11 passed in 0.89s

$ .venv/bin/python -m bench.generator
batch A  seed=20260801  payouts= 23  orders= 250  bank= 26  defects=E01,E02,E06,E07,E08,E09
           unreconciled  bank_leg=₹137,874.48  orders_leg=₹18,700.00   [cross-checked]
batch B  seed=20260901  payouts= 23  orders= 263  bank= 26  defects=E01,E02,E06,E07,E08,E09
           unreconciled  bank_leg=₹135,948.15  orders_leg=₹18,700.00   [cross-checked]

wrote data/batches/  + MANIFEST.json (sha256 per file)
  [hashes superseded 2026-08-20 by the P3 truncation fix — see the P3 entry]

$ cp data/batches/MANIFEST.json /tmp/m1.json && rm -rf data/batches
$ .venv/bin/python -m bench.generator >/dev/null && diff -q /tmp/m1.json data/batches/MANIFEST.json
  IDENTICAL — manifests match after full wipe
```

`MANIFEST.json` is committed (the only thing under `data/batches/` that is), so
regeneration is checkable on a different machine, not just this one.

**The cross-check earned its keep on first run.** It rejected batch A with
`orders leg: recomputed 25100.70 != declared 18700.00`. Cause: the recomputation
derived "which payments exist" from the order register's `payment_id` column,
which ~8% of orders drop by design — conflating *no order exists* (a real gap)
with *the export lost the reference* (recoverable on amount + date + email).
Fixed to derive from charges. Had the check been written to read the planted
list instead of recomputing, the batch would have shipped with wrong labels and
every downstream number would have inherited them.

**Not asserted:** that the planted defect *rates* are realistic. Counts are
exact and labelled; whether one E06 per 23 payouts resembles production is
unvalidated, and stays unvalidated until someone puts real format samples
beside it.

---

## Known broken / known incomplete

Track anything that is failing, stubbed, or degraded. An empty section here while gates are red means this file is stale.

| Item | State | Phase that fixes it |
|---|---|---|
| `engine/blocking.py`, `engine/subsetsum.py`, `triage/`, `mcp/`, `api/`, `events.py` | Skeleton — every module raises `NotImplementedError` naming its phase | P4–P10 |
| `Rule` has no producer | Defined and validated, nothing emits one yet | P7 |
| No blocking | The engine compares every anchor against every group. Fine at 22×23; will not scale, and blocking recall is unmeasured. | P4 |
| 8 ungrouped records unreachable | The E09 payout's rows carry no `group_ref`, so T0/T1 cannot see them. Reported, not silently dropped. | P5 |
| XLSX / OFX / QIF readers | Not implemented — `read()` raises `ReaderError` rather than returning an empty document | when a source needs them |
| `control_total` check never runs | No generated source states a total, so it only SKIPs. Untested against a real tie-out. | when a source carries one |
| `SETTLEMENT_CHART` lives in `ledger/accounts.py` | Profile data sitting in kernel code — acceptable until profiles are first-class | P10 |
| Defect rates unvalidated | Counts are exact; realism vs production formats is unchecked | ongoing — needs real format samples |
| Only 2 gateways, 1 currency | Generator is INR-only by design (ADR: FX deferred, build plan P17) | P17 decision, post-v1 |
| `bench/arms/`, `bench/metrics.py`, `bench/run.py` | Stubs | P6 |

---

## Residual risks we are carrying

From the [build plan](docs/03-BUILD-PLAN.md) problem register. These are **not** expected to close — they get reported on the scorecard and in the talk track.

| # | Risk | Current mitigation | Status |
|---|---|---|---|
| `P3` | Adapter correct on sample, wrong on tail | Roll-forward + control-total over every row; first-use approval | open |
| `P10` | Bounded subset-sum search finds one solution, misses a second | `enumerate_all_solutions`; report *unproven uniqueness* when the bound is hit | open |
| `P19` | Induced rule overfits — right on history, wrong on future | Regression gate; versioned, revocable rules | open, needs post-promotion monitoring |
| `P23` | Same team authored generator and engine | Adversarial set frozen at P0; never edited in the same commit as engine code | open — **state this limitation when reporting numbers** |

---

## Open decisions

Decisions not yet taken. Taking one means writing an ADR in `docs/decisions/`.

| Decision | Options | Blocking |
|---|---|---|
| Frontend for P9 | FastAPI+HTMX (planned) · minimal React | P9 |
| PageIndex integration for `E02` contract lookup | build · defer to v2 | P7, optional |
| Whether to adopt qm's TypeScript core | harvest patterns (current) · full adoption | post-v1 |

**Already decided and irreversible** — see `docs/decisions/`: adapters are declarative specs (ADR-001); contracts are semver'd from P1 (ADR-002).

---

## Next action

**Start P4 — blocking, and measure its recall.** Build `engine/blocking.py`:
candidate generation on amount buckets, date windows and normalized reference
keys, with Splink scoring the fuzzy dimensions (counterparty, reference).

The P4 gate is that **blocking recall is measured against batch A's labels and
printed on the scorecard** — not computed privately and omitted. A blocker that
drops a true pair caps the whole system, and the cap is invisible unless the
number is on the page every run (CLAUDE.md invariant 6).

Two things to watch. Blocking must not change any P3 number: run the gate before
and after and diff the scorecard, because a blocker that quietly improves the
match rate has changed the answer, not the search. And recall must be measured
on *candidate pairs*, not on final matches — a blocker that keeps a true pair
which T0/T1 then fails to match still has perfect recall, and conflating the two
would hide which layer lost it.

---

## Change log

Newest first. One line per session. Record what actually changed, not what was attempted.

| Date | Change |
|---|---|
| 2026-08-20 | **P3 GREEN.** T0/T1 engine, tolerance budget, independent verifier, securo baseline (raw + grouped). 90.9% auto-match, 0.00% false-match — tying the fair baseline. Found: T1 truncation was a no-op, match keys not casefolded, baseline handicapped by date choice. |
| 2026-08-20 | **P2 GREEN.** Intake: CSV + CAMT readers, spec interpreter over the closed verb set, five proofs, four hand-written specs. Contract → 1.1.0. Found: zero-row specs reporting `declared` instead of `failed`. |
| 2026-08-20 | **P1 GREEN.** Five semver'd contracts (v1.0.0) + Beancount v3 ledger. Found: `!r` lexer bug, and `tests/gates/` silently collecting zero tests. |
| 2026-08-20 | **P0 GREEN.** Generator (`bench/generator/`, 4 modules), 10 adversarial cases, 11 gate tests. Cross-check caught and fixed a real labelling bug before any batch shipped. |
| 2026-08-20 | Repo skeleton, CLAUDE.md, STATUS.md, ADR-001/002, Makefile, package layout. No functional code. |
| 2026-08-20 | Research → decision spec → architecture addendum → walkthrough → build plan. Docs in `docs/`. |
| 2026-08-20 | Code graphs built for securo (9,060 nodes) and qm (11,173 nodes); merged 20,233 / 63,339. |
