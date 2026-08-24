# STATUS — progress tracker

**Read [CLAUDE.md](CLAUDE.md) first.** This file is the live state of the build. Update it every session, at the end of the session, with real command output.

| | |
|---|---|
| **Current phase** | `P11` — open taxonomy ([plan v2](docs/06-PLAN-V2.md)). **P6–P10 are all green: the ship line is closed.** |
| **Last green gate** | **P9** — 47/47. `make verify` runs P0–P10. **259 tests, 97% coverage** over 3,179 statements. Contract **2.1.0**. |
| **Build runs?** | `make eval` closes A and B from a clean checkout — matched, **posted**, **recorded**. `make replay` rebuilds the scorecard from the decision log alone. |
| **Last verified numbers** | A/B: **90.9% auto-match, 0.00% false-match** — and the number that separates us from the baseline we tie: **exception coverage 80% vs 0%**, classification **20%** |
| **Updated** | 2026-08-24 |

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
| **P2** | Both hand-written specs ingest cleanly; a deliberately corrupted spec is caught by roll-forward, not inspection | **`GREEN`** | [below](#p2--intake--2026-08-20) |
| **P3** | **First number.** Auto-match rate + false-match rate, ours vs securo baseline, on batch A | **`GREEN`** | [below](#p3--first-number--2026-08-20) |
| **P4** | Blocking recall measured against A's labels and printed on the scorecard | **`GREEN`** | [below](#p4--blocking--2026-08-20) |
| **P5** | Planted ambiguous payout raises `E09`; solver timeouts surface as `E13`, never as silent non-matches | **`GREEN`** | [below](#p5--subset-sum--2026-08-21) |
| — | **↓ re-planned 2026-08-21 — see [docs/06-PLAN-V2.md](docs/06-PLAN-V2.md)** | | |
| **P6** | The 4 crash and 3 silent cases each produce a disposition instead; a deliberately undisposed anchor makes the completeness audit **fail** | `not started` | — |
| **P7** | Every audit attack reproduced as a failing test, then green: forged tolerance `F1`, zero signs `F2`, rejection volume `F4`, sub-paisa drift | **`GREEN`** | [below](#p7--policy--2026-08-21) |
| **P8** | The `R-EVIL` rule (tolerance ₹1,000,000, 0 broken, 93 cleared) is **refused**; a legitimate narrow rule still promotes | **`GREEN`** | [below](#p8--promotion-gate--2026-08-21) |
| **P9** | Replay a full close from the decision log alone and reconstruct the same scorecard | **`GREEN`** | [below](#p9--the-record--2026-08-24) |
| **P10** ◆ | `make eval` produces the full comparison on A and B from a clean checkout, one command | **`GREEN`** | [below](#p10--measurement--ship-line--2026-08-24) |
| — | **◆ SHIP LINE** — everything below is upside | | |
| **P11** | A novel finding gets a `PROPOSED` code, routes to an owner, and is proven unable to affect a posting | `not started` | — |
| **P12** ◆ | **The lift number.** Resolve 3 on A, approve 3 rules, re-run on held-out B, scorecard attributes rule by rule. Plus: an unseen format ingests with no configuration. | `not started` | — |
| **P13** | An external process calls `run_match`, re-derives the proof without our database — and a forged proof is refused by that same public call | `not started` | — |
| **P14** | A controller completes one close through the UI without a terminal | `not started` | — |
| **P15** | A second loop closes on profile and adapters alone; partial payment goes from exception to proof without an engine edit | `not started` | — |

◆ = the gates that carry the claim. **P6–P10 are not cuttable** — they are the difference between a
measured system and an asserted one. **P12 is not cuttable for the claim.**

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

### P9 — the record · 2026-08-24

```
$ make verify   P0 11 · P1 19 · P2 29 · P3 24 · P4 14 · P5 17 · P6 21 · P7 21 · P8 16 · P9 47 · P10 40
$ pytest -q     259 passed        $ make lint   All checks passed!
$ pytest --cov  97% over 3,179 statements

$ make eval
disposition [complete]  anchors={'excepted': 3, 'matched': 20, 'out_of_scope': 3}
                        records={'excepted': 64, 'matched': 453}  postings={'posted': 20}

journal: 23 entries, balanced, 23 loaded by beancount
  not posted: EXC-00004 (E14, ₹90259.47): no bank line — the money never reached the
              account, so this is a receivable and posting it would put cash in the
              books that is not in the bank
  not posted: EXC-00005 (E14, ₹43684.26): [same]
record: data/runs/A/decisions.jsonl
  event kinds with no producer yet: RuleInduced (P12), AdapterAuthored (P12), CodeProposed (P11)

56 events: CloseStarted=1 · SourceIngested=1 · IntakeUnverified=1 · OutOfScope=3
           MatchProven=20 · ExceptionRaised=5 · PostingWritten=23 · CloseBlocked=1
           CloseCompleted=1

$ make replay                                                            EXIT=0
replayed data/runs/A/decisions.jsonl
  batch A · profile settlement_3way · policy settlement-in@v1
  policy digest 410d4556f14782d3  (2 sources)
  deterministic: auto-match 90.9% (20/22)  false-match 0.0% (0/20)  tiers T0=18 T1=2
  exceptions: coverage 80.0% (4/5) · classification 20.0% (1/5) · ambiguity 100.0% (1/1)
  postings 23 · out of scope 3
  UNVERIFIED gateway-settlement: no substantive check could run — the source carries
             no control total and no balances
```

**The gate, executed.** `make replay` reads the file and nothing else, rebuilds
what was decided, and produces a scorecard identical to the run's — same match
count, same tier split, same coverage, same classification, same ambiguity. The
engine is made to raise while a replay runs, and the replay still returns; an
AST check keeps the replay path off the matcher's imports so the property
survives a refactor the monkeypatch would miss. Delete one `MatchProven` line
and the replayed match count drops by one, which is how you can tell the answer
came from the log rather than from recomputing it.

**Derived, not instrumented.** A log written where someone remembered to call
`emit()` records what the author was thinking about, and the refusals are exactly
what nobody is thinking about. `derive()` walks the same structures the
completeness audit walks, then checks itself against that audit: **every input
the audit gave a disposition to must be named by at least one event**, and the
close refuses to finish otherwise. That check is also what makes replay total —
the record-id → external-id map is rebuilt from the events themselves, so a
record named by no event would be unmappable on the way back.

**The books, finally.** Until this phase nothing in the close path posted. The
ledger existed and only tests used it, so "writes double-entry journal entries
for everything it can prove" was a claim with no code behind it and invariant 1
could not be evaluated. Now:

| | |
|---|---|
| a proven payout | `Dr Bank / Cr Clearing` — the gateway held it, the bank has it |
| a credit nobody can attribute | `Dr Bank / Cr Liabilities:UnappliedCash` |
| settlement the bank never received | **not posted**, with the reason printed |

The third is the one that matters. A group the gateway says it sent and no
anchor claims is a receivable, not cash; posting it would put money in the books
that is not in the account. It stays an exception and the rule says out loud why
it declined, because a posting rule that quietly skips what it cannot handle is
indistinguishable from one that has no case for it. 23 entries, balanced, loaded
by the real beancount loader. **Invariant 1 is checkable for the first time**:
the suspense balance is asserted equal to the anchor-side exception total,
derived from two different places so it cannot agree with itself.

**Append-only, and what that is worth.** Events are hash-chained: the hash covers
the content, the link covers the order, and opening a log verifies it so an
append cannot launder a tamper. An edit, a deletion, a reorder and a splice from
another run are each caught, and a finished log refuses further writes. **The
limit, stated rather than glossed:** an actor who can rewrite the whole file can
recompute the chain over anything they like. A chain proves internal
consistency, not custody — real custody needs an external anchor and there is
none. Truncating the tail is the one edit a chain alone cannot see, which is why
the log terminates in `CloseCompleted` carrying its own count.

**Policy provenance, the gap P7 left open.** P7 shipped with policy loaded from
disk and trusted. The header event now pins a sha256 of the policy *file*, and
every judged decision names the policy ref it ran under. A run judged under a
version nobody approved is visible in the record instead of invisible in memory.

**Refusals are first-class.** `R-EVIL` being turned away is the most interesting
thing that happens in a governed system, so `promote()` writes `ProposalRefused`
**before** it raises, and a verifier refusal writes `MatchRejected`. A log that
contains only what worked is a marketing document. Mutation confirms it: drop
either and the gate goes red.

**A kind with no producer is declared, not absent.** Three of the fifteen event
kinds — `RuleInduced`, `AdapterAuthored`, `CodeProposed` — are written by a model
that does not exist yet. `PRODUCERS` names the phase instead, the close prints
which kinds it could not produce, and the registry is asserted complete against
the enum at import. Same discipline as P10's absent arm.

**Two real bugs found in P8, both by chasing coverage.**

1. **`Decimal("0.00")` is falsy**, so `_tolerance_asked_for` filtered out a rule
   asking for a tolerance of exactly zero. `_apply` then left the profile alone
   and the regression reported that a rule *tightening* tolerance to zero
   changes nothing. Tightening is a legitimate proposal and the gate could not
   see what it did — audit finding `F3` pointing the other way.
2. **A P8 test that could pass by not running.**
   `test_a_rule_that_breaks_history_is_refused` was guarded by
   `if outcome.broken:` over a history where nothing could break, so the "would
   break" branch had never executed in any run. Rewritten unconditionally against
   a history built wide enough that narrowing genuinely takes a match away.

**Mutation-tested, 21/21 on P9 and 15/15 on P10 re-run.** Four survivors on the
first pass, all genuine holes, all now closed: nothing checked the stream against
its own terminator; dropping the `prev_hash` link left every test green because
deletions are also caught by the seq check (a **splice** is the case only the
link can see); the seq check itself needed a self-consistent forged log to
exercise; and the close's posting audit could be fed the very ids it was
checking — the shallow-proxy shape, in the phase that exists to make checking
possible.

**One audit, not two.** The first version re-audited from scratch after posting,
which quietly made the engine's own audit dead weight — a P10 mutation that had
been red went green. Replaced with `CompletenessReport.extend()`: the engine does
the set arithmetic over records once, and the close adds what the engine could
not know. Two answers to the same question drift, and the one nobody reads is
the one that rots.

**Contract 2.0.0 → 2.1.0.** New models only — `Event`, `EventKind`, the
per-kind payloads, `PRODUCERS`. The log is a public artifact: an external
auditor reads it without our code, so it is versioned like everything else.

**P10's numbers unchanged**: 90.9% / 0.00%, coverage 80%, classification 20%,
and both batches still reproduce to the committed manifest.

**Not built, and it matters:**
- **Retention is not built.** `data/runs/` is local scratch and gitignored. One
  log describes one close; re-running replaces it. There is no archive, no
  external anchor, and no custody story — see the chain's stated limit above.
- **`ProposalRefused` has one producer.** `promote()` writes it.
  `Policy.check_profile` and the verifier's own refusals raise without recording,
  because the contracts layer has no journal and giving it one would make the log
  a dependency of the control rather than a record of it. Wiring belongs with the
  MCP surface at P13, where every mutating call has a session to record into.
- **The postings are the settlement leg only.** `Dr Bank / Cr Clearing` is what
  this loop's sources support. The fee and revenue split belongs to the capture
  side, which is not reconciled here; inventing it would put numbers in the books
  that no source in this close supports.
- **No concurrency story.** Two closes writing one log would interleave and the
  chain would break — correctly, but the failure would be confusing rather than
  informative.
- Still toy scale: 56 events per close.

---

### P10 — measurement ◆ SHIP LINE · 2026-08-24

```
$ make verify   P0 11 · P1 19 · P2 29 · P3 24 · P4 14 · P5 17 · P6 21 · P7 21 · P8 15 · P10 40
$ pytest -q     211 passed        $ make lint   All checks passed!
$ pytest --cov  96% over 2,640 statements

$ rm -rf data/batches/A data/batches/B && ls data/batches/
MANIFEST.json                       <- a clean checkout: hashes committed, data not
$ make eval                         EXIT=0

batch A  ·  23 bank credits in scope  ·  517 settlement rows  ·  3 out of scope
  out of scope: debit — the settlement loop reconciles receipts; outgoing payments
                belong to the AP and payroll loops
true pairs (payouts banked in period): 22
blocking: 146/506 pairs (71.1% reduction) :: amount=121 date=198 reference=19
          blocking recall 100.0% (21/21 reachable true pairs kept); 1 not reachable

arm               auto-match  false-match  precision   recall  correct  false  missed
-------------------------------------------------------------------------------------
securo_raw             0.0%       0.00%      0.0%    0.0%        0      0      22
securo_grouped        90.9%       0.00%    100.0%   90.9%       20      0       2
deterministic         90.9%       0.00%    100.0%   90.9%       20      0       2
llm_only         absent — no model configured — the LLM arm and its lift number land at P12

arm               raised   exception coverage   exception classification   ambiguity detection    close    rec/s
----------------------------------------------------------------------------------------------------------------
securo_raw             0           0.0% (0/5)                 0.0% (0/5)            0.0% (0/1)     0 ms  1229483
securo_grouped         0           0.0% (0/5)                 0.0% (0/5)            0.0% (0/1)     0 ms  1463081
deterministic          5          80.0% (4/5)                20.0% (1/5)          100.0% (1/1)     6 ms    83616
llm_only         absent — no model configured — the LLM arm and its lift number land at P12

disposition [complete]  anchors={'excepted': 3, 'matched': 20, 'out_of_scope': 3}
                        records={'excepted': 64, 'matched': 453}

planted defects, one line each (labels authored at P0):
  E01 pout_00022   ₹   43684.26  surfaced as E14
  E02 pout_00014   ₹     290.07  NOT SURFACED — gateway billed above contract tier on 12 rows
  E06 ch_00493     ₹    5489.75  surfaced as E14
  E08 bl_00023     ₹    1160.00  surfaced as E14
  E09 pout_00023   ₹   87250.40  surfaced as E09, subsets agree
  E07 pout_00012   ₹   18700.00  out of scope — orders leg is not part of this loop
  model spend absent (no model call in this arm)

batch B  ·  23 in scope  ·  536 rows  ·  135/506 (73.3%)  ·  tiers T0=19 T1=1
          same rates, same coverage, same classification, same ambiguity
```

**The unflattering finding first: this phase found that we were dropping the most
interesting line on the bank statement, and four green gates had not noticed.**
`bl_00023` is the planted `E08` — a ₹1,160 credit with nothing behind it. The
runner filtered the bank side to records carrying a gateway key *before* handing
anything to the engine, so a receipt nobody can attribute was excluded **by the
very key it was missing**. It left the pipeline with no disposition and invariant
8 still reported `complete`, because the filter sat upstream of the
accountability boundary. Found only because metric 5 needs a denominator from
the labels, and the labels name a defect the run had never seen.

Fixed at the mechanism, not the call site: `run()` takes an `out_of_scope` map of
id → reason, excludes those from matching, and passes them to the audit. Scope is
now a *disposition* rather than a disappearance, `Disposition.OUT_OF_SCOPE` stops
being dead code in the production path, and the three debits appear on the
scorecard as excluded with a reason instead of vanishing.

**The number that separates us from the baseline we tie.** P3's finding was that
once securo's rule is handed the payout grouping it produces pairs identical to
ours — our matching rule contributes nothing. That has been on this page since
20 August and nothing measured what does. Now something does:

| | auto-match | exception coverage | classification |
|---|---|---|---|
| `securo_grouped` | 90.9% | **0.0% (0/5)** | 0.0% (0/5) |
| `deterministic` | 90.9% | **80.0% (4/5)** | 20.0% (1/5) |

Zero is not securo failing at exceptions; securo has no exception model, so
unmatched rows are simply absent from its output. That absence *is* the tail
being handed back, and it is what the thesis says costs the controller. The note
travels beside the number so nobody reads the 0% as a botched attempt.

**And the number that does not flatter us: classification 20%.** The engine
notices four of five planted defects and can name exactly one — `E09`, which it
reaches by arithmetic. The other three come back `E14 UNEXPLAINED`. Noticing and
naming are scored apart on purpose: counting `E14` as a classification would make
the honesty code score like an answer. **20% is P12's denominator.** The lift
number now has something concrete to be a lift *from*, which is why measurement
lands before the model edge.

**Absent, never zero.** `llm_only` is named on every run and refuses to produce a
number: `Scorecard.auto_match_rate` on an absent arm **raises** rather than
returning `0.0`, and an arm declared absent cannot carry results at all. A zero
in that row would say we ran a model and it matched nothing — a claim about a
model we never called, and one that happens to flatter us.

**Rates are not floats.** `Rate(20, 22)` prints `90.9% (20/22)`, so the lazy call
site produces the honest output. The tier split must account for every match an
arm reports or the scorecard refuses to construct — invariant 2 in scorecard
form, and it is what makes a verifier-refused match impossible to leave in the
count while dropping it from the split.

**The denominator is not ours to choose.** Declaring a hard anchor out of scope
is the obvious way to flatter coverage, so what is in scope for *measurement*
comes from the planted label's own `leg`, authored at P0. A defect on a leg this
loop does not run (`E07`, orders) is reported separately with its reason — the
same `dropped` vs `unreachable` attribution as P4, and, as there, the gate proves
it is not an escape hatch: a missed in-scope defect cannot be reclassified out.

**A circularity in my own work, caught before it shipped.** `make eval`
regenerates the batches when they are absent — but the generator writes the
manifest from the bytes it just produced, so verifying against it would compare
the batches with themselves. That is audit finding `F1` in a third costume. The
committed manifest is now restored before anything is checked, and a gate test
tampers it to prove the restore is not a no-op.

**A weak test of mine, found by mutation.** `subsets_agree` was unit-tested and
the *scoring path* was tested only on a batch where the subsets agree — so
deleting the comparison from `score_planted` and accepting any `E09` on the right
rows survived the entire gate. A helper nothing is forced to call is not a
control. 15/15 mutations caught after the fix, including: absent arm renders
zeros, rate drops its decomposition, tier split stops adding up, `E14` counts as
a classification, a missed defect is reclassified out of scope, the bank filter
comes back, input verification always passes.

**Coverage found four unexercised claims and they are now tested**, 93% → 96%.
The one that mattered: `false += 1` in `score()` had never executed — every arm
on this corpus is correct, so the metric this project calls the one that matters
was being reported by a counter that had never counted. Also: the clean-checkout
generation path, the verifier-refusal path in the deterministic arm, and securo's
date window and 1:1 exclusivity, both load-bearing for the fairness of the
baseline and neither ever fired on this corpus. One dead function deleted rather
than tested (`metrics.external_index`).

**Taken before P9, deliberately.** The plan orders P9 (the record) before P10.
P10 was taken first at the user's direction, and it is safe in this order for a
reason worth writing down: P9's gate is "replay a full close from the log alone
and **reconstruct the same scorecard**", and until this phase there was no
canonical scorecard to reconstruct. P10 defines the artifact P9 has to reproduce.
Nothing in P9 is now harder; the target is concrete.

**Not built, and it matters:**
- **The LLM-only arm is absent, so the dossier's most persuasive comparison —
  arm 3's silent-error rate against arm 4 — is unmeasured.** That is the
  strongest available result and it lands at P12, not here.
- **`E02` is unsurfaceable by this loop as configured.** The gateway paid what it
  billed, so the bank↔settlement residual closes; the variance is against the
  *contract*, which no source in this loop carries. A stated limit, not a bug,
  and the label's own note is printed beside the miss so a reader can tell.
- **Timing is one wall-clock sample per arm, not a benchmark.** The deterministic
  arm measured 2 ms, 6 ms and 30 ms across three runs on identical data. It is
  reported because metric 8 asks for it; it should not be quoted as a throughput
  figure.
- **Cost per record has no model component** and says `absent` rather than ₹0.00.
- **"Surfaced" is deliberately generous** — the run named at least one record
  involved in the defect. It answers "did a human have to look at this", which is
  the controller's question. Classification is the strict half.
- Still toy scale: 23 credits, 517 rows, one loop, one currency.

---

### P8 — promotion gate · 2026-08-21

```
$ make verify   P0 11 · P1 19 · P2 19 · P3 24 · P4 14 · P5 17 · P6 21 · P7 21 · P8 15
$ pytest -q     161 passed        $ make lint   All checks passed!

R-EVIL   tol Rs 1000000.00   1 checked, 0 broken, 1 added, 1 unverifiable
         -> REFUSED: asks for tolerance above the ceiling 0.50 in settlement-in@v1
R-023    tol Rs       0.30   1 checked, 0 broken, 1 added, 0 unverifiable
         -> PROMOTED by meera, adds 1, sample ['b:1']
```

**Both halves.** A gate that refuses everything is as useless as one that refuses
nothing, so the gate requires `R-EVIL` refused **and** a legitimate narrow rule
promoted. Only the pair shows it discriminates.

**Written red first** — the file failed on collection before any implementation
existed, then test by test as each attack was reproduced.

**The report is re-run, not read.** `RegressionReport` was attached *by the
proposer*: audit finding `F1` in a different costume, an artifact carrying its
own evidence. `regress()` now replays the rule against real history and reports
what it actually did. A rule claiming "1400 checked, 0 broken, 93 cleared" gets
measured against the history that exists.

**Additions are counted.** `matches_broken == 0` measured the one direction that
cannot see a widening rule — widening never breaks a match, it only adds.
Additions are the *point* of a rule, so they are bounded by
`policy.max_added_matches` and sampled into the approval rather than forbidden.

**Defence in depth, visible in the output.** `R-EVIL` shows `1 unverifiable`
beside the ceiling refusal: even with the ceiling check bypassed, every added
match must pass the same proof gate as any other, and that one does not.

**Promotion is an event, not a field.** `PROMOTED` is now unreachable without a
`PromotionEvent` that only `promote()` produces — carrying actor, policy ref, an
evidence hash and a sample of what the rule adds. `promote()` raises rather than
returning a flag: a caller able to ignore a boolean would be granting its own
permission.

**Contract 1.5.0 → 2.0.0, the first major.** Tightening a validator is major by
the rules in `contracts/__init__.py`, and this tightens the one that matters:
`Rule` can no longer reach `PROMOTED` on a self-attached report.
`promoted_by`/`promoted_at` moved onto the event.

**A weak test of mine, found by mutation and fixed.** Stubbing
`verify_promotion` to `return True` initially passed all 15 — because the forgery
in that test changed *two* fields at once, so the surviving guard caught it and
the disabled one was never exercised. Now each guard is forged on its own
(hash, added, broken, policy ref) and the stub fails.

**P3's numbers unchanged**, completeness still holds, batches still reproduce.

**Not built:** `regress()` models `SET_TOLERANCE` only. `NORMALIZE_KEY` can also
add matches — by making records comparable that were not — and today regresses as
a no-op, so its delta is invisible to the cap. Needs a key-rewriting interpreter,
which belongs with rule execution at P12.

---

### P7 — policy · 2026-08-21

```
$ make verify        P0 11 · P1 19 · P2 19 · P3 24 · P4 14 · P5 17 · P6 21 · P7 21
$ pytest -q          146 passed
$ make lint          All checks passed!

the four audit bypasses, re-run:
  F1 forged tolerance (residual Rs 7,466.19)  -> REFUTED
  F2 zero signs                                -> unrepresentable in Policy
  F4 49% rejection                             -> failed (['rejection_budget'])
  Rs 5.00 plug                                 -> blocked
  verdicts now name their policy: settlement-in@v1
```

**Written red first.** The gate file was authored before any of the fix and
failed on collection, then failed test-by-test as each attack was reproduced. A
test written after the code it checks tends to assert what the code already does.

**One object closed both critical findings.** `verify(proof, records, policy)`
replaces `verify(proof, records, side_signs)`. The proof's `tolerance_allowed`
became a *claim checked against the ceiling* rather than a permission honoured
(`F1`), and the sign convention comes from a frozen, named-approver `Policy` that
cannot express a zero (`F2`). Policy lives in `data/policy/settlement_3way.json`
— an asset, like an adapter spec, so a change shows up in a diff.

**The profile is now a proposal that gets checked.** `MatchProfile` gained the
validators it never had (signs ±1, both sides present), and `run()` calls
`policy.check_profile()` before attempting a single match. A profile whose signs
disagree with policy, or which asks for tolerance above the ceiling, refuses to
run — rather than producing matches the verifier then refutes, which is the right
answer reached the expensive way and only if someone looks.

**Rejection is bounded, not just legible.** A new `rejection_budget` check fails
above the policy share. It **SKIPs** when no policy is supplied and says so — a
check that silently passes without its policy is the `F1` shape again.

**Sub-paisa drift is posted or blocked, never absorbed.** Beancount carries a
default tolerance of its own, so an entry off by ₹0.005 loaded with zero errors.
Residue at or below the threshold now posts to `Expenses:Rounding` with the
amount in metadata; above it the close is blocked. Build-plan problem `P16`,
finally built.

**Mutation-tested one-for-one.** Reverting each fix fails exactly the test
written for it: trust the proof's tolerance → `F1` test; accept a zero sign →
`F2` test; budget never fires → `F4` test; ignore the threshold → both rounding
tests.

**A shallow proxy in my own gate, caught by that mutation.** The rounding test
asserted `"Expenses:Rounding" in result.text` — which passes regardless, because
every chart account appears in the `open` directives. It survived the mutation
that disabled rounding entirely. Replaced with an assertion on the metadata key
that only exists on an entry the rounding path actually touched, and the
mutation now fails both tests.

**Found by the pre-P7 verification sweep, not by P6's gate:** a **missing file**
raised `FileNotFoundError`, not `ReaderError`, so `ingest()` did not catch it and
the run still died. P6 caught only `ReaderError`; the likeliest source failure of
all — the download that never happened — sailed past. Now catches `OSError` and
`csv.Error` too, with gate cases for a missing file and a directory.

**P3's numbers are unchanged** (90.9% / 0.00%), completeness still holds, and the
batches still regenerate to the committed hashes.

**Not built:** policy is loaded from disk but nothing verifies its signature or
provenance — a tampered policy file is trusted. That belongs with P9's decision
log, which is where "which policy version judged this" becomes replayable.

---

### P6 — completeness · 2026-08-21

```
$ make verify
=== gate P0 ===  11   === gate P1 ===  19   === gate P2 ===  19
=== gate P3 ===  24   === gate P4 ===  14   === gate P5 ===  17
=== gate P6 ===  19

$ .venv/bin/python -m pytest -q     123 passed
$ make lint                         All checks passed!

batch A  ·  22 gateway credits  ·  517 settlement rows
true pairs (payouts banked in period): 22
blocking: 146/484 pairs (69.8% reduction) :: amount=121 date=198 reference=19
          blocking recall 100.0% (21/21 reachable true pairs kept); 1 true pair(s) not reachable at all — the source declared no group: ['pout_00023']

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
  deterministic: exceptions raised: E09 ₹87250.40, E14 ₹84769.72, E14 ₹90259.47, E14 ₹43684.26
  deterministic: 146/484 pairs (69.8% reduction) :: amount=121 date=198 reference=19
  deterministic: 8 record(s) the source left ungrouped — unreachable by T0/T1, reconstructed by T2 subset-sum

disposition [complete]  anchors={'excepted': 2, 'matched': 20}  records={'excepted': 64, 'matched': 453}

exceptions (deterministic arm):
  E09  ₹    87250.40  2 distinct subsets sum to this credit within tolerance; no unique answer exists
        subset of 4: ['gateway-settlement:509', 'gateway-settlement:510']...
        subset of 4: ['gateway-settlement:513', 'gateway-settlement:514']...
  E14  ₹    84769.72  no strategy produced a match and the engine cannot say why
  E14  ₹    90259.47  group 'pout_00011' was not claimed by any anchor in this period
  E14  ₹    43684.26  group 'pout_00022' was not claimed by any anchor in this period
```

**The audit found two silent cases on the real batch that the register missed.**
The register was built from synthetic probes; run against batch A, invariant 8
immediately flagged **1 undisposed anchor and 64 undisposed records** — the E06
duplicate payout's bank line, and the rows of two groups (`pout_00011`,
`pout_00022`) that no anchor claimed. Four phases of green gates on this data and
57 records were ending every run mentioned nowhere.

That is the argument for the invariant over the register: a list of anticipated
cases ages badly, and this one was already stale by the time it was written.

**`E14 UNEXPLAINED` rather than a guess.** The engine knows an item did not match
and what it is worth; it does not know *why*. Force-fitting `E06` or `E01` would
put a guess where rules key on codes — a wrong code routes to the wrong owner and
may fire the wrong rule. `E14` carries the facts it has (amount, row count,
total) and leaves classification to triage. It joins `E09` and `E13` as an
honesty code: "I do not know" said out loud beats a confident wrong answer.

**All five crash cases now report instead of raising.** `ingest()`'s docstring
promised this since P2 and was false — the reader raised straight through, so one
unopenable file killed a whole close. A source that cannot be read is now a
failed source, not a failed run.

**Header-only files fail rather than reading as a clean month.** A failed fetch
and a genuinely empty period are indistinguishable from the file, so this
escalates instead of guessing.

**Contract 1.2.0 → 1.4.0** (1.3.0 was `DECIMAL_MINOR`). Two new enum members,
both so the system can say "I do not know" out loud: `ExceptionCode.E14_UNEXPLAINED`
and `ParseVerb.UNMAPPABLE`.

**One semantics bug of mine, caught by its own test.** `UNMAPPABLE` first failed
individual *rows*, so on a split Dr/Cr source the debits still parsed and intake
reported `declared`, `ok=True` — a partial ingest masking that a whole class of
rows was unexpressible. Declaring a column unmappable is a statement about the
**spec**, not the rows. It now stops the source before reading and says which
column and what to do next.

**Mutation-tested both ways.** Skipping the disposition pass fails 7 tests;
making the audit always report `complete` fails 2, including the load-bearing
one. The gate asserts directly that a deliberately undisposed anchor makes the
audit fail — an audit that only ever passes is decorative.

**P3's numbers are unchanged**: 90.9% auto-match, 0.00% false-match, and the
batches still regenerate to the committed hashes.

**Not built:** the completeness audit covers anchors, records and sources. It
does not yet cover *journal entries* — nothing asserts that every proven match
produced a posting. That belongs with P9's decision log.

---

### P5 — subset-sum · 2026-08-21

```
$ .venv/bin/python -m bench.run --batch A
batch A  ·  22 gateway credits  ·  517 settlement rows
true pairs (payouts banked in period): 22
blocking: 146/484 pairs (69.8% reduction) :: amount=121 date=198 reference=19
          blocking recall 100.0% (21/21 reachable true pairs kept); 1 true pair(s) not reachable at all — the source declared no group: ['pout_00023']

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
  deterministic: exceptions raised: E09 ₹87250.40
  deterministic: 146/484 pairs (69.8% reduction) :: amount=121 date=198 reference=19
  deterministic: 8 record(s) the source left ungrouped — unreachable by T0/T1, reconstructed by T2 subset-sum

exceptions (deterministic arm):
  E09  ₹    87250.40  2 distinct subsets sum to this credit within tolerance; no unique answer exists
        subset of 4: ['gateway-settlement:509', 'gateway-settlement:510']...
        subset of 4: ['gateway-settlement:513', 'gateway-settlement:514']...
```

`make verify` runs P0–P5, 104 tests. The ambiguous payout is **never
committed**: T2 finds two subsets, raises `E09` carrying both, blocks the close.

**The solver reports what it established, not what it found.** Five outcomes:
`UNIQUE` (enumeration ran out), `AMBIGUOUS` (two or more subsets — a data
finding), `UNPROVEN` (one found, a bound stopped the search), `TIMEOUT`, `NONE`.
`UNPROVEN` and `TIMEOUT` map to **`E13`**, not `E09`: they are findings about our
compute, and reporting a capacity limit as a data finding is the specific
failure this phase existed to prevent. All three bounds — wall clock,
enumeration cap, candidate cap — are set up front and each is exercised, so the
capacity path is not dead code.

**Mutation-tested twice.** Committing the first solution without proving
uniqueness fails 6 tests; reporting a capacity limit as `E09` fails 2.

**The solver over-reported ambiguity until told about cohesion.** It first found
**4** subsets, not the 2 in the labels — free to pair a charge from one half
with a fee from the other. The data carries the linkage: a fee shares its
charge's `payment_id`. Constraining rows that share a key to move together
reduced it to exactly the two labelled subsets. Without it a real 200-row payout
explodes combinatorially — a scaling bug, not a cosmetic one. The key is named
by the profile, so the engine stays domain-agnostic.

**Contract 1.1.0 → 1.2.0: a P1 modelling error of mine, corrected.** P1 required
`E09.alternatives` to be **disjoint**. That is wrong — two subsets that share a
row can both sum to the target, and that is genuine ambiguity. The solver
produces overlapping alternatives whenever a row belongs to more than one viable
subset, so the validator would have forced the engine to *hide real ambiguity to
satisfy a contract*. Now requires **distinct**. A loosening, so minor; the P1
gate was updated to assert the corrected semantics rather than deleted.

**The no-float rule caught `SolverBounds.max_seconds: float`.** Rule 4 says do
not suppress it, so the float went instead: durations are integer milliseconds
in `engine/` now, for the same reason money is integer minor units. A blunt rule
that cannot be silenced is doing its job.

**Not built:** the wall-clock `TIMEOUT` branch is reachable but unexercised —
the candidate cap refuses first at realistic sizes.

---

### P4 — blocking · 2026-08-20

```
$ .venv/bin/python -m bench.run --batch A
batch A  ·  22 gateway credits  ·  517 settlement rows
true pairs (payouts banked in period): 22
blocking: 146/484 pairs (69.8% reduction) :: amount=121 date=198 reference=19
          blocking recall 100.0% (21/21 reachable true pairs kept); 1 true pair(s) not reachable at all — the source declared no group: ['pout_00023']

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
  deterministic: 146/484 pairs (69.8% reduction) :: amount=121 date=198 reference=19
  deterministic: 8 record(s) the source left ungrouped — unreachable by T0/T1, deferred to subset-sum at P5
```

Batch B: 72.1% reduction, same recall, same scores. `make verify` runs P0–P4,
87 tests.

**Recall is printed above the match rates**, so it cannot be skimmed past, and a
dropped true pair exits the runner non-zero — a cap on everything downstream is
not a footnote (CLAUDE.md invariant 6). Blocking is asserted to leave every P3
number identical: a blocker that changes the answer is a matching rule wearing a
blocker's clothes.

**One true pair is not reachable at all, and that is reported separately.**
`pout_00023` is the E09 payout: its settlement rows carry no `group_ref`, so no
`(anchor, group)` pair was ever presented to the blocker. Counting it as a
blocking drop would blame the wrong layer — the same conflation the P3 hand-off
note warned about. So `dropped` and `unreachable` are separate fields, both
printed.

**That split is an attribution, not an escape hatch, and the gate proves it.**
`test_unreachable_cannot_absorb_a_real_blocking_failure` removes a pair whose
group *is* declared and asserts it lands in `dropped`. Mutating `recall()` to
classify every loss as unreachable fails 5 tests including that one; mutating
`build()` to silently drop a single pair fails 2. Without those, "100% recall"
would be a number the code could always produce.

**Splink deferred, with a reason.** The plan pairs blocking with Splink for
probabilistic scoring of counterparty and reference. There is currently no case
in the corpus where a probabilistic score changes an outcome: T1 already refuses
when two groups could absorb a credit, and genuine ambiguity (identical amounts,
identical dates) carries no signal for Splink to find. Adding it now would be an
untested dependency that passes because it never runs — the same hazard as the
dead T1 tier at P3 and the uncollected gate files at P2. It goes in when the
corpus has a case that needs it.

---

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

**Correction, 2026-08-21.** This entry called the verifier "independent". It is
independent of the *proof's residual claim* — mutation-testing proves that — but
**not** of the caller's policy: it reads `tolerance_allowed` from the proof and
takes `side_signs` from the caller. See findings F1/F2 in
[docs/04-CONTROL-PLANE-AUDIT.md](docs/04-CONTROL-PLANE-AUDIT.md). The numbers
below stand for the honest path; the independence claim was too broad.

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
| **F1 `verify()` reads tolerance from the proof** | **CRITICAL.** A proof declaring `tolerance_allowed: 9999999` passes with a ₹7,466.19 residual. Defeats the independent-verification claim. | before P7 |
| **F2 `verify()` takes signs from the caller** | **CRITICAL.** `side_signs={0,0}` makes every match verify. `MatchProfile` has zero validators. | before P7 |
| **F3 regression gate blind to widening** | **HIGH.** `promotable` only checks `matches_broken == 0`; widening tolerance adds matches without breaking any. A ₹1,000,000 tolerance rule promotes cleanly. | before P7 — blocks it |
| **F4 rejection has no budget** | **HIGH.** A reasoned reject rule discarded 251 of 517 rows and reported `declared`/`ok=True`. Row conservation checks reasons, not volume. | before P7 |
| **F5 missing verb fails plausibly** | Verb added (1.3.0), class permanent: a closed vocabulary lacking a verb picks the nearest and returns a plausible number. Needs an `UNMAPPABLE` escalation. | before P7 |
| **`NORMALIZE_KEY` regresses as a no-op** | `regress()` models `SET_TOLERANCE` only. A key-rewriting rule can add matches whose delta the cap never sees. | P12 |
| ~~Policy provenance unverified~~ | **Closed at P9.** The header event pins a sha256 of the policy file and every judged decision names its policy ref, so a run under an unapproved version is visible in the record. A *signature* is still absent — the digest proves what ran, not who approved it. | signing: post-v1 |
| ~~Completeness does not cover postings~~ | **Closed at P9.** The close posts, and the audit gained a postings dimension: a proven match with no journal entry makes it fail. | resolved |
| **Partial payment / 1:N have no strategy** | Both now raise `E14` rather than going silent, but neither can be *matched*. They become configuration at P15. | P15 |
| **A novel finding still cannot be named** | `E14` is the honest placeholder; a real registry with a lifecycle is P11. | P11 |
| No control plane | `approved_by` / `attested_by` are contract fields with no enforcement code. No validate/constrain/approve/execute/escalate/record layer exists. | before P7 |
| `triage/`, `mcp/`, `api/` | Skeleton — every module raises `NotImplementedError` naming its phase | P12–P14 |
| **No retention or custody for the log** | `data/runs/` is local scratch. One log per close, replaced on re-run. No archive, no external anchor: the chain proves internal consistency, not custody. | post-v1 |
| **`ProposalRefused` has one producer** | `promote()` records it. `check_profile` and verifier refusals raise without recording — the contracts layer has no journal by design. | P13 (a session to record into) |
| **Postings cover the settlement leg only** | `Dr Bank / Cr Clearing`. The fee/revenue split belongs to the capture side, which this loop does not reconcile. | P15 |
| **No concurrency story for the log** | Two closes writing one log interleave and break the chain — correctly, but confusingly. | when a server exists |
| Wall-clock `TIMEOUT` branch unexercised | The candidate cap refuses first at realistic sizes, so the clock branch is reachable but untested. | when a slow case exists |
| `Rule` has no producer | Defined and validated, nothing emits one yet | P7 |
| Splink not integrated | Deferred with a reason — no corpus case where probabilistic scoring changes an outcome. See the P4 entry. | when a case needs it |
| 8 ungrouped records | Reconstructed by T2. On batch A they resolve to two valid subsets, so they stay an `E09` exception rather than a match — correctly. | resolved |
| Blocking untested at scale | 69.8% reduction on 22×23. The index shape is right; the constants are unvalidated above a few hundred rows. | when a large corpus exists |
| XLSX / OFX / QIF readers | Not implemented — `read()` raises `ReaderError` rather than returning an empty document | when a source needs them |
| `control_total` check never runs | No generated source states a total, so it only SKIPs. Untested against a real tie-out. | when a source carries one |
| `SETTLEMENT_CHART` lives in `ledger/accounts.py` | Profile data sitting in kernel code — acceptable until profiles are first-class | P15 |
| Defect rates unvalidated | Counts are exact; realism vs production formats is unchecked | ongoing — needs real format samples |
| Only 2 gateways, 1 currency | Generator is INR-only by design (ADR: FX deferred, build plan P17) | P17 decision, post-v1 |
| **Everything is validated at toy scale** | 22 payouts, 517 settlement rows, 2 gateways, 1 currency, 1 loop. Blocking constants, solver bounds and tolerance policy are all unvalidated above a few hundred rows. | needs a large corpus |
| **No application surface** | No UI (P14), no MCP (P13), no persistence, no API. This is a library plus a benchmark harness, not something anyone can operate. | P13–P14 |
| **Zero model code** | `triage/` is three stubs at 0% coverage. The entire agentic claim is unbuilt. | P12 |
| **The LLM-only arm is unmeasured** | The dossier's most persuasive result — arm 3's silent-error rate against arm 4 — needs a real model. Reported `absent` on every run so the hole is on the page, never `0.0%`. | P12 |
| **Exception classification is 20%** | The engine notices 4 of 5 planted defects and can name 1. The other three are `E14 UNEXPLAINED`. This is the honest baseline P12 has to beat, not a bug. | P12 |
| **`E02` is unsurfaceable by this loop** | Fee variance is against the *contract*; no source in the settlement loop carries one, so the bank↔settlement residual closes cleanly. Stated limit, printed beside the miss. | needs a contract source |
| **Timing is a single wall-clock sample** | The deterministic arm measured 2/6/30 ms across three runs on identical data. Metric 8 asks for it; it is not a throughput figure. | when a benchmark exists |

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

**The ship line is closed.** P6–P10 are all green: the system measures itself,
accounts for every input, posts what it proves, and can be re-derived from its
own record. Everything from here is upside.

**Start P11 — open taxonomy.** Before the agent, because the agent needs to name
a novel finding without crashing.

1. **Exception-code registry** with a lifecycle replacing the closed enum:
   `PROPOSED → PROVISIONAL → PROMOTED → RETIRED`.
2. `PROPOSED` may label and route; **cannot fire a rule or affect a posting**.
3. Contract **major bump** — breaking. Do it while there are no external
   consumers.

**Gate:** a novel finding gets a `PROPOSED` code, appears in triage, routes to an
owner, and is proven unable to affect a posting. Promotion requires a named human
and a written definition.

Three things P9 leaves ready for it. `CodeProposed` already exists as an event
kind with `P11` named as its producer, so the registry has somewhere to write.
The posting rules are now the place to prove a `PROPOSED` code cannot reach the
books — a claim that was unfalsifiable while nothing posted. And `E14` is doing
the registry's job badly today: 4 of 5 planted defects surface and 1 is named,
so **classification 20% is the number P11 and P12 have to move.**

---

## Change log

Newest first. One line per session. Record what actually changed, not what was attempted.

| Date | Change |
|---|---|
| 2026-08-24 | **P9 GREEN — the ship line is closed (P6–P10 all green).** Append-only decision log, hash-chained; 15 typed event kinds derived by set arithmetic over the audit's own structures, not by instrumenting the happy path. `make replay` rebuilds the scorecard from the log alone with the engine made to raise. **The close now posts** — 23 balanced entries, unattributable credits to suspense, settlement the bank never received deliberately not posted with the reason printed — which makes invariant 1 checkable for the first time. Policy bytes pinned in the header, closing P7's provenance gap. **Found two real bugs in P8: `Decimal("0.00")` is falsy so a tolerance-tightening rule regressed as a no-op, and a P8 test that could pass by not running.** 21/21 mutations caught after closing four genuine holes; coverage 96% → 97%. Contract → 2.1.0. |
| 2026-08-24 | **P10 GREEN ◆ SHIP LINE.** `make eval` from a clean checkout: 4 arms, 8 metrics, A and B. Rates carry their decomposition; the LLM arm reports absent and refuses to produce a number; the tier split must account for every match. **Found: the runner was filtering the bank side before the completeness audit could see it, so the planted `E08` — a ₹1,160 credit with nothing behind it — left every run undisposed while invariant 8 read `complete`.** First measurement of the differentiator: exception coverage 80% vs the baseline's 0%; classification 20%, which is P12's denominator. 15/15 mutations caught; coverage 93% → 96%. |
| 2026-08-21 | **P8 GREEN.** Promotion gate: regression re-run rather than read, additions counted and capped, added matches must verify, promotion is an event with an evidence hash. `R-EVIL` refused, narrow rule promotes. Contract → **2.0.0** (first major). Mutation found a weak test of mine that changed two fields at once. |
| 2026-08-21 | **P7 GREEN.** `Policy` as a versioned frozen asset; `verify(proof, records, policy)`; profile validators + `check_profile`; rejection budget; rounding threshold. All four audit bypasses closed and mutation-tested 1:1. Contract → 1.5.0. Also fixed a missing-file crash P6's gate had missed, and a vacuous assertion in my own P7 gate. |
| 2026-08-21 | **P6 GREEN.** Completeness audit (invariant 8) + `E14_UNEXPLAINED` + `UNMAPPABLE`; readers report instead of raising; header-only files fail. Contract → 1.4.0. The audit found 2 silent cases on the real batch the register had missed. |
| 2026-08-21 | **Re-planned P6–P15** ([docs/06-PLAN-V2.md](docs/06-PLAN-V2.md)). Control plane becomes phases of its own ahead of the model edge; the decision log moves earlier; the ship line moves to P10. Old P6→P10, P7→P12, P8→P9+P13, P9→P14, P10→P15. |
| 2026-08-21 | **Failure register.** 19 novel inputs probed: 5 crash, 3 finish silently, 2 finish wrong, 9 handled. Added **invariant 8** (every input has a disposition) to CLAUDE.md — one completeness check that catches unenumerated cases. |
| 2026-08-21 | **Audit.** Attacked the system at P5: five reproducible control bypasses, two defeating the verifier. Root cause — artifacts check themselves, policy comes from the caller. Remediation 1–4 blocks P7. Contract → 1.3.0 (DECIMAL_MINOR). |
| 2026-08-21 | **P5 GREEN.** T2 subset-sum with CP-SAT, five outcomes, cohesion constraint, E09/E13 split. Contract → 1.2.0 (disjoint→distinct, correcting a P1 modelling error). No-float rule caught a float in engine. |
| 2026-08-20 | **P4 GREEN.** Blocking with unioned blocks, ~70% search reduction, 100% recall on reachable pairs, P3 numbers unchanged. `dropped` vs `unreachable` split, mutation-tested both ways. Splink deferred with a reason. |
| 2026-08-20 | **P3 GREEN.** T0/T1 engine, tolerance budget, independent verifier, securo baseline (raw + grouped). 90.9% auto-match, 0.00% false-match — tying the fair baseline. Found: T1 truncation was a no-op, match keys not casefolded, baseline handicapped by date choice. |
| 2026-08-20 | **P2 GREEN.** Intake: CSV + CAMT readers, spec interpreter over the closed verb set, five proofs, four hand-written specs. Contract → 1.1.0. Found: zero-row specs reporting `declared` instead of `failed`. |
| 2026-08-20 | **P1 GREEN.** Five semver'd contracts (v1.0.0) + Beancount v3 ledger. Found: `!r` lexer bug, and `tests/gates/` silently collecting zero tests. |
| 2026-08-20 | **P0 GREEN.** Generator (`bench/generator/`, 4 modules), 10 adversarial cases, 11 gate tests. Cross-check caught and fixed a real labelling bug before any batch shipped. |
| 2026-08-20 | Repo skeleton, CLAUDE.md, STATUS.md, ADR-001/002, Makefile, package layout. No functional code. |
| 2026-08-20 | Research → decision spec → architecture addendum → walkthrough → build plan. Docs in `docs/`. |
| 2026-08-20 | Code graphs built for securo (9,060 nodes) and qm (11,173 nodes); merged 20,233 / 63,339. |
