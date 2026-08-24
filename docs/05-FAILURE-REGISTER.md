# Where the Run Goes Quiet — failure register

Date: 2026-08-21 · Probed at P5 · Published: https://claude.ai/code/artifact/f23cb3b6-be3a-400b-9be4-999162743893

Nineteen novel inputs thrown at the working system. Every row is a run, not a reading.

| Outcome | Count | Meaning |
|---|---|---|
| **Crash** | 5 | Run dies, no diagnosis surface |
| **Silent incomplete** | 3 | Run finishes, item unexplained — looks like success |
| **Silent wrong** | 2 | Run finishes, answer wrong |
| **Handled** | 9 | Declared, blocked or escalated correctly |

The nine that work are the ones with gates. The ten that don't are the ones I never wrote a case
against.

---

## Register

### Input — reader layer

| Case | Outcome | What happens |
|---|---|---|
| Source is XLSX / OFX / QIF | **CRASH** | `ReaderError: reader kind 'xlsx' is not implemented yet`, raised out of `ingest()` — whose docstring claims it "never raises on a bad document". One unsupported file kills the whole close. |
| Malformed XML | **CRASH** | `ReaderError` before any proof object exists. Nothing to show a human. |
| Completely empty file | **CRASH** | `header_row 1 is past the end`. A zero-byte download takes the run with it. |
| `header_row` misconfigured | **CRASH** | Same path. A spec error becomes a run-level crash. |
| **Header present, zero data rows** | **SILENT** | `declared · parsed=0/0 · ok=True`. The zero-rows guard is `rows_in_file > 0 and not records`, so an empty export passes as clean. A failed fetch reads as a quiet month. |
| Column in spec absent from file | Handled | `failed` |

### Input — spec and verb layer

| Case | Outcome | What happens |
|---|---|---|
| Date format the tokens cannot express (`14-Aug-2026`) | Handled | `failed` — but the message blames the data, not the missing month-name token |
| **No verb fits the column** | **WRONG** | No way to say so. Nearest verb is used. Integer minor units parsed as major = **100× wrong**, every check passing (no control total to contradict it). |
| Currency symbol not in `strip` | Handled | `failed` |
| Two currencies in one source | Handled | `failed` — `type_domain` catches it |

### Matching — a strategy that does not exist

| Case | Outcome | What happens |
|---|---|---|
| **Partial payment** — ₹600 credit vs ₹1,000 invoice | **SILENT** | `matches=0 exceptions=[] unmatched=1`. Lands in `unmatched_anchors`, no exception. `E04 PARTIAL_PAYMENT` is in the taxonomy and **nothing ever produces it**. |
| **One invoice, two credits (1:N)** | **SILENT** | `matches=0 exceptions=[] unmatched=2`. T2 reconstructs N:1 only; the inverse has no strategy and no exception. |
| Negative payout (refunds exceed charges) | Handled | Matched at T1 |
| Zero-net payout | Handled | Matched at T1 |
| All candidates zero, target zero | Handled | `ambiguous`, 3 solutions → `E09` |
| Two candidates both within tolerance | Handled | `ambiguous` → `E09` — tolerance does not hide it |

### Taxonomy and ledger

| Case | Outcome | What happens |
|---|---|---|
| **A finding with no code** (e.g. a promotional rebate) | **CRASH** | `ValueError: 'E14' is not a valid ExceptionCode`. The agent's only options are force-fit into `E02` — wrong owner, possibly wrong rule — or silence. |
| **Sub-paisa residue** (entry off by ₹0.005) | **WRONG** | `blocked=False`, zero errors. Beancount's default tolerance absorbs it. Build-plan P16 called for a rounding account with a policy threshold; never built. |
| Chart missing a role | Handled | `ValidationError` at construction |
| Entry before accounts open | Handled | `blocked` |

**The three silent cases share one shape:** an input enters, no code path claims it, and the run ends
without saying so. Every individual check answers its own question correctly. Nobody asks *"did
everything that came in get an answer?"*

---

## Invariant 8 — every input has a disposition

When a run ends: every **source** is verified, declared or failed; every **record** is matched,
attached to an exception, or explicitly out of scope with a reason; every **anchor** is matched or
carries an exception. A run that completes with an undisposed input is a bug in the system, not a
finding about the data.

Same shape as the invariant that already works — *unreconciled value equals the balance-assertion
gap*. Both are completeness checks computed two independent ways; both fail loudly rather than
reporting a plausible number.

**Why this matters more than the register:** a list of anticipated cases ages badly, because the next
novel input is by definition not on it. A completeness invariant catches cases nobody enumerated.
Partial payment and 1:N stop being silent the moment the run must account for every anchor it was
given — not because anyone predicted those two.

---

## The disposition ladder

Every failure resolves to exactly one rung. Crash is not on the ladder, and neither is silence.

| Rung | Meaning |
|---|---|
| **1 · PROPOSE** | The agent expresses what is missing: a new adapter spec, a verb request with column + samples, a new exception code with a definition, a new matching strategy. Nothing has effect yet. |
| **2 · ABSORB** | Policy already permits it. Residue under the rounding threshold posts to the rounding account; tolerance inside the ceiling is consumed and recorded. |
| **3 · DECLARE** | Proceed with the gap stamped — unverified intake, an accepted out-of-policy tolerance, a source with no redundancy. Counted separately, never folded into the headline. |
| **4 · ESCALATE** | Stop with an owner and a reason: `E09`, `E13`, rejection budget exceeded, a proposal policy refuses. The close is blocked and says why. |

A reader that cannot open a file returns an `IntakeProof` with a `FAIL` check and the run continues on
the other sources — one bad file quarantines itself.

---

## How each case routes

| Case | Agent proposes | Policy constrains | Human | Rung |
|---|---|---|---|---|
| Unsupported format | An adapter spec, or a conversion step | Reader kinds allowed; no codegen (ADR-001) | First-use approval | 1 → 2 |
| Malformed / empty file | Nothing — a fetch failure, not a mapping problem | Zero records from a non-empty source FAILs | Re-fetch | 4 |
| Header-only file | Nothing | A source producing zero records fails regardless of row count | Notified | 4 |
| **No verb fits** | `UNMAPPABLE` with column name + 3 sample values | Cannot silently substitute a near-miss verb | Approves a new verb | 1 → 4 |
| **Partial payment** | Classify `E04`; propose a partial-settlement strategy | Strategy cannot post; must emit a proof | Approves the strategy once | 1 → 4 |
| **1:N settlement** | Propose an inverse-subset strategy | Same contract and bounds as T2 | Approves the strategy | 1 → 4 |
| **No code fits** | A `PROPOSED` code with definition + evidence | `PROPOSED` may label and route; **cannot fire a rule or affect a posting** | Promotes or rejects | 1 → 4 |
| Sub-paisa residue | Nothing — deterministic | Rounding threshold; above it becomes `E03` | Sets threshold once | 2 or 4 |
| Rejection above budget | A narrower reject rule | Max rejection rate per source | Approves an exception | 4 |
| Ambiguity / compute bound | Explain and rank | Already correct today | Attests a resolution (`P2`) | 4 |

**In every row the agent names something and proposes a way to handle it.** It never decides, never
posts, never widens its own permission. That surface is enough to absorb every case in the register —
including unenumerated ones — because `PROPOSED` and `UNMAPPABLE` are general escape hatches rather
than case-specific handlers.

---

## Remediation

| # | Change | Closes | Size |
|---|---|---|---|
| 1 | Readers return a failed `IntakeProof` instead of raising | 4 crashes | Small |
| 2 | A source producing zero records fails regardless of row count | Header-only silence | Trivial |
| 3 | **Completeness audit at end of run** — invariant 8, computed independently | Both silent matching cases, plus every future one | Small; highest value per line |
| 4 | `UNMAPPABLE` outcome in the verb layer, carrying column + samples | No-verb-fits | Small |
| 5 | Rounding threshold in policy; residue above it becomes `E03` | Sub-paisa drift | Small |
| 6 | Exception-code registry with lifecycle, replacing the closed enum | Cannot-name-a-finding | Medium · major bump |
| 7 | Declarative strategy pipeline | Missing strategies, permanently | Larger |

One through five are small and independent of the control-plane work in
[04-CONTROL-PLANE-AUDIT.md](04-CONTROL-PLANE-AUDIT.md). **Three first** — it is the only item that
catches failures nobody has thought of, and would have found both silent matching cases without
anyone writing a partial-payment test.

---

## Not covered

Nineteen cases I could think to try, on interfaces I built. Says nothing about concurrency,
multi-tenant leakage, a source changing format mid-file, adversarial content in a narration field, or
FX. Same limitation as every audit here: one person probing their own design.
