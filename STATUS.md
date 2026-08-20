# STATUS — progress tracker

**Read [CLAUDE.md](CLAUDE.md) first.** This file is the live state of the build. Update it every session, at the end of the session, with real command output.

| | |
|---|---|
| **Current phase** | `P1` — contracts + canonical Record + ledger |
| **Last green gate** | **P0** — 11/11, `make verify` |
| **Build runs?** | Generator does. Engine is still skeleton. |
| **Last verified numbers** | batch A bank-leg ₹137,874.48 · orders-leg ₹18,700.00 (cross-checked) |
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
| **P1** | Round-trip a hand-built journal through Beancount; an unbalanced entry is *rejected*; a wrong closing balance *blocks* the close | `not started` | — |
| **P2** | Both hand-written specs (CAMT, Shopify) ingest cleanly; a deliberately corrupted spec is caught by roll-forward, not inspection | `not started` | — |
| **P3** ◆ | **First number.** Auto-match rate + false-match rate, ours vs securo baseline, on batch A | `not started` | — |
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
  A/bank_camt    b0268af7b211e6aa      B/bank_camt    cd0e0f359f8efe9e
  A/bank_csv     8c2bd2666b79f485      B/bank_csv     f7d00b55450e4b92
  A/labels       fd939089aef25a28      B/labels       725b21bf036fe6ed
  A/orders       cbbf6d4b5b7a10ee      B/orders       cbe3d63cb2c6b703
  A/settlement   71d7a9bc1bb5724c      B/settlement   42f1ccddfbe3b367

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
| `src/recon/**` | Skeleton — every module raises `NotImplementedError` naming its phase | P1–P10 |
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

**Start P1.** Define the five contracts in `src/recon/contracts/` — `Record`, `Proof`,
`Exception`, `Rule`, `AdapterSpec` — as Pydantic v2 models, semver'd from the first
commit (ADR-002). Then wire Beancount v3 and the balance assertion.

The P1 gate is not "the models import." It is: a hand-built journal round-trips
through Beancount, a deliberately unbalanced entry is **rejected**, and a wrong
closing balance **blocks** the close rather than warning.

Design the contracts against `data/batches/A/labels.json` — it already contains
every field the engine will need to produce, so the label schema is a working
specification for the `Proof` and `Exception` shapes.

---

## Change log

Newest first. One line per session. Record what actually changed, not what was attempted.

| Date | Change |
|---|---|
| 2026-08-20 | **P0 GREEN.** Generator (`bench/generator/`, 4 modules), 10 adversarial cases, 11 gate tests. Cross-check caught and fixed a real labelling bug before any batch shipped. |
| 2026-08-20 | Repo skeleton, CLAUDE.md, STATUS.md, ADR-001/002, Makefile, package layout. No functional code. |
| 2026-08-20 | Research → decision spec → architecture addendum → walkthrough → build plan. Docs in `docs/`. |
| 2026-08-20 | Code graphs built for securo (9,060 nodes) and qm (11,173 nodes); merged 20,233 / 63,339. |
