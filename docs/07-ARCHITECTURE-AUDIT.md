# The Root Cause — architecture audit

Date: 2026-08-25 · Method: graphify code graph (1876 nodes / 4272 edges / 113 communities),
runtime tracing, and five reproducible experiments. Prototypes in the session scratchpad;
every number below came from executing something.

---

## The finding in one sentence

**This system applies the certifying-algorithm discipline to exactly one of its five decision
types, and to none of the others — so every control over the other four could be green while
guarding an effect that never happened.**

Matching is a certifying algorithm and a good one. `verify()` re-derives leg subtotals and the
residual from the records, refuses a proof claiming more tolerance than policy allows, refuses
double-counted and off-side records, and **runs in-band on every match in every close** —
`bench/arms/deterministic.py:61`. An unverified match is dropped and recorded. That is why the
matching engine has never been the thing that broke.

Nothing else has a checker that runs on real output.

---

## The evidence

### 1. The governance and model layers do not execute in a close

A runtime trace of one real `close("A")` executes **135 of 254** functions in `src/recon`.
Never executed:

| module | never executed | what it is |
|---|---|---|
| `engine/promotion.py` | **20/20** | the entire promotion gate |
| `triage/induce.py` | 10/10 | rule induction |
| `triage/classify.py` | 9/9 | exception classification |
| `triage/client.py` | 7/7 | the model edge |
| `triage/normalize.py` | 5/5 | adapter synthesis |
| `engine/taxonomy.py` | **7/7** | propose · accept · promote · retire |

Outside `tests/`, `evaluate()` is called only by `promote()`, and `regress()` only by
`verify_promotion()`. `induce`, `author_spec`, `attest`, `apply_attested`, `accept` and `retire`
have **zero** non-test callers.

This is the mechanism behind every governance bug found in the last two days. A control that only
tests drive can be checked on its *inputs*; nothing observes its *outputs*, because in production
it has none. "Promotion was ceremony", "three actions promoted and did nothing", "`raise_advisory`
was declared modelled and implemented nowhere", "the gate counted only what a change breaks" —
one cause, four symptoms.

### 2. There is no application

`bench/run.py:close()` is the only thing that assembles intake → tiers → ledger → journal →
scorecard. `src/recon/api/` and `src/recon/mcp/` are **0-byte files**. `src/recon` is a library
with no application, and the benchmark harness is the product's only executable form — so
"in-band" has no band to be in.

### 3. A `P1 RULE` proof's rule dependency is not verified — reproducible

`verifier.py` never mentions `rule_id`, `rule_version`, `provenance`, or `P1`.

```
verify(genuine P1 proof)                  -> proven
verify(rule_id -> "R-DOES-NOT-EXIST")     -> proven
verify(tier relabelled P1 -> P0)          -> proven
```

The tier is enforced at *construction* (`tiers._provenance_for`) and never at *verification*.
P13's gate says a forged proof must be refused by the public call; a forged **tier** is not.
This directly undermines invariant 3.

The cause is witness incompleteness: after a suppression the legs contain only the *kept* rows,
so the arithmetic is true and the claim is under-determined. The witness does not carry what the
rule removed.

### 4. P11's open registry cannot grow at runtime

`engine/taxonomy.py`'s lifecycle has no non-test caller and the registry is never written back.
`data/taxonomy/codes.json` is read-only in practice. The gate is green because tests call
`propose()` directly.

### What is *not* a proxy

`verify()` is sound (checked line by line). There are **zero** `NotImplementedError` in `src/` —
nothing is a declared stub. The engine is honest; the layers around it are disconnected.

---

## What the literature says

**Certifying algorithms** — McConnell, Mehlhorn, Näher & Schweitzer. A certifying algorithm
returns output `y` *and* a witness `w`; a checker `C` accepts `(x, y, w)` iff `w` proves
`y = f(x)`. The checker must be simple and independent of the producer. The line that matters
here: *"A certifying program can be tested on every input. The test is whether the checker
accepts the triple."* **If the checker runs in-band on every decision, production is the test** —
which is exactly why matching never broke and everything else did.

**Open Policy Agent** — policy ships as a *signed bundle* (`.signatures.json` of file digests)
verified against a key configured **out-of-band**; an unverifiable bundle is not activated. Each
decision-log event carries bundle metadata, so a decision names the exact bundle that produced
it. That is the shape our rule store and taxonomy should take.

**Training–serving skew** — the canonical two-code-path failure: offline and online compute the
same thing by different code, and offline metrics improve while online stalls. The accepted fix
is one definition consumed by both paths. Notably even feature stores do not fully fix it,
because the two contexts keep different owners and failure modes — which argues for *one path*,
not two paths sharing a helper.

**Hexagonal architecture** — a test harness is a legitimate *driving adapter*. It should call the
core through an inbound port. Ours **is** the core.

---

## The architecture

**One principle: every decision emits a witness, and every witness is checked in-band by a
checker that does not trust the producer and takes its inputs independently.**

Four changes, in dependency order.

### A1 · One entry point — `src/recon/close.py`
Move orchestration out of `bench/run.py` into the library. The benchmark, the API and the MCP
server become driving adapters that call it. This is what makes "in-band" mean anything, and it
is a precondition for A2 and A3.

### A2 · Complete the match witness, and check it — **validated**
Add `rule_bundle_digest` to `Proof`; extend `verify()` with three clauses:

1. a witness whose group has records missing from its legs may not claim `P0 ARITHMETIC`;
2. a `P1` proof must name a rule present in the cited bundle;
3. re-running that rule over the group must reproduce exactly the partition the proof claims.

**Derive the exclusion from `records`, never read it from the proof.** My first prototype rebuilt
the population from the witness and both tamper cases passed — that is audit finding `F1` (a check
reading its input from the artifact it checks), reintroduced by me while fixing it. v2 derives it,
needs no new `excluded` field, and leaves nothing to forge.

Measured, v2:

| case | verdict |
|---|---|
| genuine P1 witness | proven |
| `rule_id` forged | **refuted** |
| tier laundered to P0 | **refuted** |
| `rule_id` dropped, tier kept | **refuted** |
| bundle swapped (rule absent) | **refuted** |
| bundle rule swapped underneath same id | **refuted** |
| 20 honest P0 proofs, unruled close | 20/20 proven |
| 20 proofs, shipped close | 20/20 proven |

### A3 · In-band effect checking for the rule bundle — **validated**
At close time recompute each promoted rule's observable effect on real output and record it. Zero
observable effect is a finding on the close, not a silent pass.

| case | verdict |
|---|---|
| advisory onto a P0-derived exception (cannot land) | **refused** — re-coded 0 |
| `book_to` on rows no exception names | **refused** — moved no posting |
| `normalize_key` that changes nothing | **refused** — no match, no exception moved |
| advisory that fires on nothing | **refused** — fires on 0 rows |
| shipped `R-DUP-06` | OK |
| a real suppression | OK |

Report, don't refuse, per close: a rule legitimately inert on *one* batch is not a bug; a rule
inert on *every* batch is. Policy sets the bar; the close records the fact either way.

### A4 · Signed bundles for `data/rules/` and `data/taxonomy/` — OPA pattern
`.signatures.json` of file digests, key configured out-of-band, unverifiable bundle not activated.
Closes the last `xfail` (`test_policy_carries_a_signature`) and makes the store tamper-evident.
A2 then cites the bundle digest, so every decision names the bundle that produced it.

### What I would *not* do
- **Do not add more controls to the promotion gate.** Every control added this week was correct
  and not one addressed the root cause. The gate is not the problem; its disconnection is.
- **Do not build the attestation path first.** A2 is what makes `P2 ATTESTED` checkable; without
  it an attested suppression is exactly as unverifiable as a ruled one.

### On `E02`, the one inexpressible rule
Separate problem, smaller than it looks. Predicates are single-record; `E02` ("billed above
contract tier") needs a fee compared to a rate on a sibling record. Add a **group-aggregate field
family** (`group.sum`, `group.count`, `group.ratio_to`) to the closed vocabulary. It stays
declarative, interpreted by hand-written code, no `eval` — ADR-001 is untouched.

---

## Honesty

A2 and A3 were validated by running prototypes against the real batches, with the regression
numbers above. **A1 and A4 are argued from precedent and are not validated.** The graph's static
call analysis was unreliable and was discarded in favour of runtime tracing — it reported
`tiers.py` 15/15 unreachable, which is false, because the AST extractor misses aliased imports.
The doc↔code edges (149 of them) did land and were used. And this remains one person auditing
their own design.
