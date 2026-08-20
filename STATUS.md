# STATUS — progress tracker

**Read [CLAUDE.md](CLAUDE.md) first.** This file is the live state of the build. Update it every session, at the end of the session, with real command output.

| | |
|---|---|
| **Current phase** | `P2` — intake: parsers, spec interpreter, five proofs |
| **Last green gate** | **P1** — 19/19. `make verify` runs P0+P1, 30 tests. |
| **Build runs?** | Generator and ledger do. Engine and intake are still skeleton. |
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
| **P1** | Round-trip a hand-built journal through Beancount; an unbalanced entry is *rejected*; a wrong closing balance *blocks* the close | **`GREEN`** | [below](#p1--contracts--ledger--2026-08-20) |
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
| `src/recon/intake/`, `engine/`, `triage/`, `mcp/`, `api/`, `events.py` | Skeleton — every module raises `NotImplementedError` naming its phase | P2–P10 |
| Contracts have no producers | `Record` (P2), `Proof` (P3), `Rule` (P7) are defined but nothing emits them yet | P2, P3, P7 |
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

**Start P2.** Build the intake layer: readers for CSV and CAMT.053, the
`AdapterSpec` interpreter (`intake/spec.py` + `verbs.py`), and the five ingestion
proofs. Hand-write two specs — one for `bank_icici.csv`, one for `orders.csv` —
with **no model involved**. The interpreter must exist before anything authors
specs for it.

The P2 gate is not "the files parse." It is: both hand-written specs ingest
cleanly, **and** a deliberately corrupted spec — point `amount` at the wrong
column — is caught by the roll-forward proof rather than by someone reading the
output. Write the corruption case first; if roll-forward doesn't catch it, the
proof is decorative.

`data/batches/A/bank_icici.csv` already carries a running balance column and two
trailing blank rows, so roll-forward and row-conservation both have real targets.
`ParseVerb.SIGN_FROM_COLUMN` exists for its split Withdrawal/Deposit columns.

---

## Change log

Newest first. One line per session. Record what actually changed, not what was attempted.

| Date | Change |
|---|---|
| 2026-08-20 | **P1 GREEN.** Five semver'd contracts (v1.0.0) + Beancount v3 ledger. Found: `!r` lexer bug, and `tests/gates/` silently collecting zero tests. |
| 2026-08-20 | **P0 GREEN.** Generator (`bench/generator/`, 4 modules), 10 adversarial cases, 11 gate tests. Cross-check caught and fixed a real labelling bug before any batch shipped. |
| 2026-08-20 | Repo skeleton, CLAUDE.md, STATUS.md, ADR-001/002, Makefile, package layout. No functional code. |
| 2026-08-20 | Research → decision spec → architecture addendum → walkthrough → build plan. Docs in `docs/`. |
| 2026-08-20 | Code graphs built for securo (9,060 nodes) and qm (11,173 nodes); merged 20,233 / 63,339. |
