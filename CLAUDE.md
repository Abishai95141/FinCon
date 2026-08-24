# CLAUDE.md — standing context

**Read this file first, every session, before doing anything else. Then read [STATUS.md](STATUS.md).**

This file is *stable*. It changes only when an architectural decision changes — not when code changes. If you find yourself editing it to describe progress, you want STATUS.md instead.

---

## What this is

A **reconciliation controller** for Track 04 (AI Finance Controller). It closes a three-way match — invoice/order register ↔ gateway settlement ↔ bank statement — writes double-entry journal entries for everything it can prove, and returns a ranked exception worklist with a machine-checkable proof attached to every decision.

**The thesis, in one line:** incumbents automated the match and handed back the tail. We automate the tail, and make every resolution permanent.

**The architecture, in one line:** open intake, verified commit. The model proposes; a deterministic engine proves; a human decides.

Full reasoning in `docs/`. Read those when you need *why*; read this file when you need *what* and *the rules*.

---

## Non-negotiable rules

### 1. No shallow proxies. Ever.

A shallow proxy is anything that makes a gate *look* passed without the underlying capability existing. This project's entire pitch is honest verification. Faking a result here is not a shortcut — it is a contradiction of the product.

**Specifically banned in this codebase:**

| Banned | Why it's fatal here | Do instead |
|---|---|---|
| A `verify()` / `prove()` that returns `True` without re-deriving | The proof gate is the product | `raise NotImplementedError` until it re-derives from raw records |
| Hardcoding a match, amount, or count to make a test green | Makes the scorecard a lie | Fix the engine, or mark the test `xfail` with the reason |
| Mocking the model and reporting agent metrics | The lift number is the claim | Metrics come from real calls, or they are not reported |
| A demo path that differs from the real path | Whatever we demo must be what we built | One code path; record a replay tape from the real run |
| Test fixtures derived from actual output | Circular — the test asserts whatever we happen to do | Fixtures come from `bench/generator/` labels, authored independently |
| Subset-sum returning the first solution found | Silently produces confident wrong answers | Enumerate; if the bound is hit, report *unproven uniqueness* |
| Reporting match rate without false-match rate and tier split | The headline number alone is gameable | Every rate ships with its decomposition |
| Marking a phase gate green without pasting the command output | Unverifiable claims accumulate into a broken build | Gate status in STATUS.md requires the output that proves it |
| `except: pass` around a verification step | Turns a failure into a silent success | Let it raise; a failed verification is information |
| Generator emitting only cases the engine handles | Teaching to the test | Adversarial set is authored at P0 and never edited to match the engine |
| A check reading its threshold from the artifact it checks | The artifact grants itself permission — this is audit finding `F1` | Thresholds come from policy, passed in alongside the artifact |
| A check taking its policy from the caller | The caller may be the agent — audit finding `F2` | Policy is a separate, versioned input the proposer cannot supply |
| A gate measuring only one direction of harm | Widening a tolerance breaks nothing and ruins everything — audit finding `F3` | Count what a change *adds*, not only what it breaks |
| Counting a rejection as "accounted for" without bounding its volume | 251 of 517 rows discarded, `ok=True` — audit finding `F4` | A reason makes a rejection legible; a budget makes it bounded |
| An input that ends a run with no disposition | The run exits zero and the scorecard looks clean — see invariant 8 | Every source, record and anchor is matched, excepted, or explicitly out of scope |
| An unmeasured thing reported as **zero** | A zero says we ran it and got nothing. That is a claim, and it flatters us for free — found at P10 on the LLM arm | Report **absent**, naming the phase that will measure it, and make the number *raise* rather than return |
| Filtering an input before the completeness audit can see it | Invariant 8 only sees what it is handed; a filter in the caller is a silent drop with extra steps — found at P10 | Hand the engine everything; declare exclusions `out_of_scope` with a reason, and print the count |

**Stubs are fine. Fake implementations are not.** An unimplemented function must `raise NotImplementedError("P5 — subset-sum solver")` naming the phase that will fill it. It must never return a plausible value.

**If you cannot complete something, say so in STATUS.md and leave it failing.** A red gate with an honest note is worth more than a green gate that lies. This is the rule that matters most — every other rule here is downstream of it.

### 2. The model never writes to the ledger

The model produces *proposals* — `AdapterSpec`, `Exception[]`, `RuleProposal`. Every one is checked by deterministic code before it has any effect. There is no code path where model output becomes a posting without passing a proof or a named human approval.

### 3. No generated code is executed

Adapters are **declarative specs** interpreted by hand-written code with a closed vocabulary of parse verbs. No `eval`, no `exec`, no `importlib`, no dynamic code from a model. An unknown verb is a spec error, not an execution. This is one of two irreversible decisions — see `docs/decisions/`.

### 4. Decimal, never float

`float` is banned in `src/recon/engine/` and `src/recon/ledger/`. Money is `decimal.Decimal` at boundaries and integer minor units at rest. There is a lint rule; do not suppress it.

### 5. Contracts are semver'd from P1

`src/recon/contracts/` is the public surface. Changing a field is a breaking change with a version bump, not an edit. This is the second irreversible decision.

### 6. Test for real

Unit tests on real inputs. Property tests on invariants. E2E against a generated batch with known labels. A test that only exercises a mock has tested the mock.

---

## Vocabulary

Compaction loses these first. They are load-bearing — use them exactly.

**Match tiers** — how a match was found
| | |
|---|---|
| `T0` | Exact — amount + date + reference |
| `T1` | Tolerant — within a stated tolerance budget |
| `T2` | Subset-sum — N:1, reconstructing which rows sum to a payout |
| `T3` | Unmatched → exception queue |

**Proof tiers** — provenance of a committed decision. Never a binary gate.
| | |
|---|---|
| `P0 ARITHMETIC` | Residual closes to zero from raw records; re-derivable by a third party |
| `P1 RULE` | A promoted, regression-tested rule fired |
| `P2 ATTESTED` | A named human approved it |
| `P3 DECLARED` | Accepted with a stated gap (unverified intake, out-of-policy tolerance) |

**The rule is "never move silently," not "refuse what you can't prove."** A close may complete carrying P2 and P3 items — it may not carry them undeclared. Every headline rate ships with its tier split.

**Exception codes** — closed enum *today*; P11 replaces it with a registry whose codes have a lifecycle, so an agent can name a novel finding without it having any power until promoted
| | | | |
|---|---|---|---|
| `E01` Timing / in-transit | `E02` Fee variance vs contract | `E03` FX / rounding | `E04` Partial payment |
| `E05` Overpayment / on-account | `E06` Duplicate | `E07` Chargeback post-period | `E08` Missing remittance |
| `E09` **Netting ambiguity** | `E10` Reference corruption | `E11` Counterparty alias | `E12` Wrong entity |
| `E13` Solver timeout | | | |

`E09` and `E13` are the honesty codes. `E09` means multiple valid subsets exist and there is no correct answer to pick. `E13` means we hit a compute bound — a capacity limit must never masquerade as a data finding.

**Ingestion proofs** — five checks, no knowledge of format or domain required
row conservation · control-total tie-out · balance roll-forward · type/domain validity · idempotence

---

## Invariants

These must hold at all times. A change that breaks one is a bug, not a trade-off.

1. **Unreconciled value == balance-assertion gap.** If they diverge, the system itself is wrong and must say so rather than post.
2. **A match without a passing proof is not a match.** It does not appear in the match count.
3. **Every committed decision carries a proof tier.** No untiered commits.
4. **Re-ingesting a file changes nothing.** `doc_hash` idempotence.
5. **A rule cannot be promoted if it breaks a historical match.** The regression gate is not advisory.
6. **Blocking recall is reported on every run.** An unmeasured blocker silently caps the whole system.
7. **The engine is domain-agnostic.** Anything domain-specific belongs in a profile, not in `engine/`.
8. **Every input has a disposition.** When a run ends, every source is verified/declared/failed, every record is matched / attached to an exception / explicitly out of scope with a reason, and every anchor is matched or carries an exception. A run that completes with an undisposed input is a bug in the system, not a finding about the data. Crash and silence are both violations — see `docs/05-FAILURE-REGISTER.md`.

---

## File map

```
CLAUDE.md              ← you are here. Stable. Read first.
STATUS.md              ← progress tracker. Read second. Update every session.
Makefile               ← every command you need
docs/
  00-RESEARCH-DOSSIER.md      why this problem, what exists
  01-DECISION-SPEC.md         problem/solution/impact/trade-offs
  02-ARCHITECTURE-ADDENDUM.md open intake, verified commit; proof tiers; substrate
  03-BUILD-PLAN.md            stack, model config, 26 failure modes (phases superseded by 06)
  04-CONTROL-PLANE-AUDIT.md   five reproducible control bypasses; the trust-class redesign
  05-FAILURE-REGISTER.md      19 probes — where a novel input crashes, goes silent, or goes wrong
  06-PLAN-V2.md               ← THE PLAN. P6–P15, re-planned after the audits.
  README.md                   index + the published artifact URLs
  decisions/                  ADRs — one per notable or irreversible choice
src/recon/
  contracts/     Pydantic models = the public semver'd surface
  intake/        readers · spec interpreter · closed parse verbs · five proofs
  ledger/        beancount wiring, balance assertions, posting rules
  engine/        blocking · tiers T0–T3 · subset-sum · tolerance budget · verifier
  triage/        model edge — normalize, classify, induce. Proposals only.
  profiles/      loop definitions as data (settlement_3way, gstr2b)
  mcp/           FastMCP server — verify_proof is stateless and public
  api/           FastAPI + OpenAPI
  events.py      typed event emission
bench/
  generator/     synthetic batches + complete labels + manifest verification
  adversarial/   authored at P0, before the engine. Never edited to match it.
  arms/          four ablation arms incl. the securo baseline and the absent LLM arm
  planted.py     exception coverage / classification / ambiguity, scored vs P0 labels
  rate.py        a rate that cannot be printed without its decomposition
  metrics.py     the eight metrics
  run.py         `make eval`
tests/
  unit/ property/ e2e/
data/
  batches/       generated, gitignored
  adapters/      cached adapter specs (JSON, committed — they are assets)
repos/           cloned baselines (gitignored)
graphify-out/    code graph (gitignored)
```

---

## Session loop

Run this every session. It is short on purpose.

1. **Read** `CLAUDE.md` (this file), then `STATUS.md`.
2. **Verify** the last green gate still passes — `make verify`. If it doesn't, fixing that is the work.
3. **Pick** the next unmet gate from STATUS.md. One gate at a time.
4. **Build** it.
5. **Run** the gate command. It passes or it doesn't — no interpretation.
6. **Update** STATUS.md: gate status, the command output that proves it, real numbers, anything now known-broken.
7. **Commit** with the phase and gate in the message.

**When compaction hits:** re-read CLAUDE.md and STATUS.md. Between them they carry the vocabulary, the eight invariants, the file map, and exactly where the build stands. Nothing else needs to survive.

**Do not skip ahead.** The plan is [docs/06-PLAN-V2.md](docs/06-PLAN-V2.md) — phase numbers after P5 were reassigned on 2026-08-21, so anything citing the old P6–P10 is stale. The order encodes three rules: what catches *unknown* failures comes before what fixes known ones; governance lands before the agent; measurement lands before the agent. Building the model edge before the control plane means demonstrating the opposite of the thesis.

---

## Commands

```bash
make setup        # uv sync, install hooks
make verify       # every currently-green gate, re-run
make gate P=3     # run the gate for phase N
make eval         # ablation runner — 4 arms, 8 metrics, batches A and B
make gen          # regenerate synthetic batches from seed
make test         # unit + property
make e2e          # end-to-end on a generated batch
make lint         # ruff + the no-float rule
make graph        # refresh the graphify code graph
```

If a command doesn't exist yet, the phase that creates it hasn't run. Don't fake it — add it when its phase lands.

---

## Irreversible decisions

Two. Both in `docs/decisions/`. Changing either invalidates a load-bearing argument, so raise it before building rather than after.

| ADR | Decision | Rests on it |
|---|---|---|
| `ADR-001` | Adapters are declarative specs; no generated code is executed | The entire security argument |
| `ADR-002` | Contracts are semver'd public objects from P1 | Compoundability — other systems build on them |

Everything else is a preference to change on evidence. Record notable changes as a new ADR rather than editing an old one.

---

## Working preferences

- **Finish the whole task.** Report completion only when it is fully done. If part is blocked, do the rest and say plainly what's missing and why.
- **Don't narrow scope silently.** If the ask looks wrong, say so in a sentence and keep building under stated assumptions.
- **Numbers come from runs, not estimates.** If you state a figure, it came from executing something. Compute arithmetic rather than eyeballing it.
- **Match the surrounding code.** Comment density, naming, idiom.
- **One gate per commit** where practical, so a regression bisects cleanly.
