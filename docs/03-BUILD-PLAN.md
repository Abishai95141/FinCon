# Build Order and Blast Radius — phases, stack, failure modes

Date: 2026-08-20 · Follows [02-ARCHITECTURE-ADDENDUM.md](02-ARCHITECTURE-ADDENDUM.md)

> **§2 (phases) is superseded from P6 onward by [06-PLAN-V2.md](06-PLAN-V2.md).**
> **§1 (stack and model config) is superseded outright** — it described the stack
> we planned to build on, and four of its choices did not survive contact. Named
> here rather than rewritten, because §3's problem register is still live and
> refers back to these choices:
>
> | §1 says | Actually |
> |---|---|
> | Model `claude-opus-5`, ~50¢/close at Opus pricing | `deepseek-v4-flash` (`triage/client.py`). The cost table below is Opus arithmetic and does not describe a close today. |
> | polars · splink · postgresql + SQLAlchemy · ofxparse · calamine · beanquery · lxml | All removed from `pyproject.toml` on 2026-08-26 — declared and imported nowhere, which reads as capability this project does not have. `tests/property/test_dependencies.py` now fails if an unused one reappears. |
> | Screens: FastAPI + HTMX | Server-rendered HTML with **no JavaScript at all** and no build step. |
> | Store: postgresql 16 | No database. The durable record is a file; users live in Cognito. |
>
> §0 (declarative adapters), §3 (the 26 failure modes) and §4 (the two
> irreversible decisions) stand unchanged.

---

## 0. One correction the research forced

I said the model would "author an adapter." Taken literally that means an LLM writing executable Python that then runs over financial data — a remote-code-execution hole with a language model on the far end.

The standard mitigations don't hold. RestrictedPython is *"notoriously difficult to get right and often bypassed over time as new attack vectors are discovered"* and *"generally insufficient on its own for truly untrusted code from an LLM."* Containers share the host kernel. Firecracker microVMs work but are a lot of infrastructure for a hackathon.

**The fix is to remove the code, not sandbox it.** The model emits a **declarative adapter spec** — JSON drawn from a fixed vocabulary of field mappings, parsers and transforms. A hand-written deterministic interpreter executes it. No `eval`, no import, no filesystem, no network — nothing to escape, because nothing arbitrary was generated. This is the "safe grammar" idea (STELP line of work) taken to its endpoint, and it costs nothing in flexibility for tabular/XML sources, which is every source in scope.

```json
{ "source": "icici-current",
  "reader": { "kind": "csv", "encoding": ["utf-8", "latin-1"], "header_row": 1 },
  "fields": [
    { "to": "date",             "from": "Txn Date",        "parse": "date:DD-MM-YY", "tz": "Asia/Kolkata" },
    { "to": "amount",           "from": "Withdrawal Amt.", "parse": "decimal", "strip": ["₹", ","], "sign": "dr" },
    { "to": "amount",           "from": "Deposit Amt.",    "parse": "decimal", "strip": ["₹", ","], "sign": "cr" },
    { "to": "counterparty_raw", "from": "Narration",       "parse": "text" },
    { "to": "reference_raw",    "from": "Narration",       "parse": "regex", "pattern": "/RAZORPAY/(pout_[A-Za-z0-9]+)/" },
    { "to": "running_balance",  "from": "Closing Balance", "parse": "decimal", "strip": [","] } ],
  "reject": [ { "when": "row_blank", "reason": "blank_footer" } ],
  "currency": "INR" }
```

Interpreter: ~400 lines, hand-written, deterministic, unit-tested. Parse verbs are a **closed set** — an unknown verb is a spec error, not an exec.

**Deferred fallback:** a source the spec language can't express (bespoke binary, PDF needing layout logic) gets a human-written adapter in v1. Sandboxed codegen for those is a v2 decision with real infrastructure, not something to sneak in under time pressure.

---

## 1. Stack

**Python-only for v1.** Beancount, Splink and OR-Tools are all Python; single-language removes the two-language seam flagged as a risk. We harvest qm's *patterns* (approval gates, audit, replay) rather than adopting its TypeScript core — adoption stays available later.

| Layer | Choice | Why | Risk it carries |
|---|---|---|---|
| Runtime | `Python 3.12` · `uv` | Every core dep is Python; real lockfile | — |
| **Ledger** | `beancount` v3 + `beanquery` | Double-entry, balance assertions, `bean-check`. The assertion mechanic *is* the close gate. | v3 split out `beangulp`/`beanquery` and removed `bean-extract`/`bean-identify` from core — importers are scripts now. Pin versions; v2 tutorials don't apply. |
| Tabular | `polars` | Strict typing, lazy scan, no silent float coercion | Less familiar than pandas; Decimal needs care |
| Money | `decimal.Decimal`, integer minor units at rest | Float in a ledger is a correctness bug | Discipline not library — needs a lint rule |
| Parsers | `ofxparse`, `lxml` (CAMT), `calamine`/`openpyxl`, stdlib `csv` | Harvested from securo's 892-line `import_service.py` incl. encoding fallbacks + junk-row filters | `ofxparse` old/lightly maintained; securo runs it in production |
| Entity resolution | `splink` 4 (DuckDB) | Fellegi–Sunter with **explainable** weights; DuckDB = no infra | Splink 4 API differs from 3 — ignore v3 examples |
| **Solver** | `ortools` CP-SAT | Subset-sum with tolerance; `enumerate_all_solutions` is exactly the `E09` detector | NP-hard — needs hard time limits + cardinality bounds |
| API | `fastapi` + `pydantic` v2 | OpenAPI free; Pydantic models *are* the semver'd contracts | Contract changes become breaking early |
| **MCP** | `fastmcp` | ~70% of MCP servers; returned Pydantic model auto-generates `outputSchema` and validates `structuredContent` | standalone `fastmcp` vs official `mcp` SDK; use Streamable HTTP not SSE |
| Store | `postgresql` 16 + SQLAlchemy 2 | Scoping, audit, rule versions, proof history | — |
| **Model** | `claude-opus-5` | See config below | Cost/latency — quantified below |
| Eval | `pytest` + custom ablation runner | Scaffolding patterns from FinBalance (Apache-2.0) | — |
| Screens | FastAPI + HTMX | Two screens; a build pipeline for two screens wastes the window | Less polished than React on stage |
| Deferred | PageIndex · GraphRAG | Contract lookup for `E02`; counterparty graph for `E11` | Cut first |

### Model configuration

| Job | Model | Effort | Output | Volume/close |
|---|---|---|---|---|
| Adapter spec synthesis | `claude-opus-5` | high | Structured — `AdapterSpec` | 0 cached · ~2 calls on novel source |
| Exception triage | `claude-opus-5` | medium | Structured — `Exception[]`, code is an enum | 1 batched call |
| Rule induction | `claude-opus-5` | high | Structured — `RuleProposal` | 1 per resolution |

Every call uses `output_config.format` with a JSON schema — structured proposals, never prose the engine parses. Adaptive thinking on. Prompt caching on the stable prefix (profile, taxonomy, tolerance policy); Opus 5's cacheable minimum is 512 tokens (half Opus 4.8's), so even short prefixes cache.

**Two Opus 5 gotchas.** Thinking is **on by default** and `max_tokens` caps thinking + response together — a tight `max_tokens` truncates mid-answer. And do **not** disable thinking to save cost: with it off the model occasionally writes a tool call into visible text instead of emitting a `tool_use` block, so the call silently never runs while the turn reports success. Lower `effort` is the cost lever; disabling thinking is not.

### Cost per close (verified arithmetic)

```
Opus 5   $5.00/MTok in    $25.00/MTok out

triage           ~15K in +  4K out  →  $0.175
rule induction   ~24K in +  9K out  →  $0.345   (3 resolutions)
────────────────────────────────────────────────
steady-state close                     ~$0.520
+ novel source   ~10K in +  4K out  →  ~$0.150 each, once ever
```

~50¢ of model spend per close. Not the constraint; engineering time is. Cost lever if triage volume grows: `claude-sonnet-5` at $3/$15 ($2/$10 introductory through 2026-08-31) — your call, not a default.

---

## 2. Phases

Each phase ends with a gate that either passes or doesn't. Order chosen so the first real number lands at P3 of 10, and the adapter interpreter exists before the model that writes specs for it.

| # | Phase | Gate |
|---|---|---|
| **P0** | Synthetic generator + ground truth. Batches A (working) and B (held out). Adversarial set authored here, before the engine exists. | Generator emits A and B with complete labels; adversarial cases present; a second person can regenerate identical batches from a seed. |
| **P1** | Contracts + canonical `Record` + ledger. `Record`/`Proof`/`Exception`/`Rule`/`AdapterSpec` as Pydantic models, semver'd from day one. | Round-trip a hand-built journal through Beancount; an unbalanced entry is *rejected*; a wrong closing balance *blocks* the close. |
| **P2** | Intake — parsers, spec interpreter, five ingestion proofs. Two hand-written specs (CAMT, Shopify), no model yet. | Both specs ingest cleanly; a deliberately corrupted spec (wrong amount column) is caught by roll-forward, not inspection. |
| **P3** | Engine T0/T1 + proof verifier + securo baseline arm. | **First number on the board.** Auto-match rate + false-match rate, ours vs baseline, on batch A. |
| **P4** | Blocking + Splink. | Blocking recall measured against A's labels and **printed on the scorecard** — not computed privately. |
| **P5** | T2 subset-sum + ambiguity detection. CP-SAT, hard time limit, cardinality bounds, `enumerate_all_solutions`. | Planted ambiguous payout raises `E09` rather than a confident wrong answer; solver timeouts surface as exceptions. |
| **P6** | Metrics + ablation runner. Eight metrics, four arms, one command. | `make eval` produces the full comparison on A and B from a clean checkout. |
| — | **◆ MINIMUM SHIPPABLE LINE** | everything below is upside, in this order |
| **P7** | Model edge — adapter synthesis, triage, rule induction. | **The lift number.** Resolve 3 on A, approve 3 rules, re-run on held-out B, scorecard attributes improvement rule by rule. |
| **P8** | MCP surface + events. `verify_proof` as a stateless public call. | An external process calls `run_match` and re-derives the proof without touching our database. |
| **P9** | Screens + audit export. | A controller completes one close through the UI without a terminal. |
| **P10** | Second profile — GSTR-2B. | A second loop closes with zero kernel code changed — profile and adapters only. |

**If the window closes early:** cut P10, then P9 (demo from CLI), then P8. **P7 is not cuttable** — without it there is no agent and no lift number, which is the entire claim. If P5 overruns, ship T0/T1 with subset-sum stubbed to "escalate always" and say so on the scorecard; a declared gap is in-thesis, a hidden one is not.

---

## 3. Problem register — 26 named failure modes

`residual` = mitigation is partial and we carry risk.

### Intake

| # | Problem | What stops it |
|---|---|---|
| P1 | **Model-authored code is an RCE hole.** Sandboxes are hard to get right and routinely bypassed. | Declarative spec + fixed interpreter. Nothing arbitrary generated → nothing to escape. **closed** |
| P2 | **Prompt injection through file content.** A narration or PDF can carry "ignore previous instructions" — indirect injection is the dominant real-world attack; the exploitable shape is *private data + untrusted content + external communication*. | Break the third leg: the triage model has **no egress and no ledger write path**. Source text is data, never concatenated into instructions. Worst case is a wrong classification a human sees — the proof gate means it can't become a posting. **closed by architecture** |
| P3 | Adapter correct on the 50-row sample, wrong on the tail (documented LLM sensitivity to row/column arrangement). | Roll-forward + control-total tie-out over *every* row. First-use human approval on raw-vs-parsed. **residual** |
| P4 | Source with no control total, no closing balance, no redundancy. | Admit, stamp `UNVERIFIED_INTAKE`, inherit `P3 DECLARED`, count separately. **by design** |
| P5 | Encoding failures — Latin-1 bank files, BOM, mojibake. | securo's decode-chain; encoding recorded in the spec so re-ingest is deterministic. **closed** |
| P6 | Excel date serials, locale decimals (`1.234,56`), two-digit years across a century boundary. | Explicit parse verbs; century pivot is stated policy, not inference. **closed** |
| P7 | Adapter silently degrades after a bank changes its export format. | Adapter-fault detection: historically-90% source now matching at 3% quarantines the adapter instead of emitting thousands of exceptions. **closed** |

### Matching

| # | Problem | What stops it |
|---|---|---|
| P8 | **Subset-sum is NP-hard.** 100 candidate rows ≈ 10³⁰ subsets. | CP-SAT with hard wall-clock limit, cardinality bounds, amount-bucket pre-filtering. **bounded** |
| P9 | Solver times out and the item looks "unmatched" — indistinguishable from a real exception. | Distinct state `E13 SOLVER_TIMEOUT` with the bound that was hit. A capacity limit must never masquerade as a data finding. **closed** |
| P10 | **Ambiguity that looks unique.** Bounded search finds one subset and stops; a second exists but was never enumerated. This is the mode that silently produces a confident wrong answer. | `enumerate_all_solutions` against a fixed objective. If enumeration itself hits the bound, report *possible* ambiguity rather than uniqueness. **residual — the honest report is "we did not prove uniqueness"** |
| P11 | Float drift in tolerance comparison. | `Decimal` at the boundary, integer minor units internally; lint rule bans `float` in the engine package. **closed** |
| P12 | Blocking silently drops a true pair, capping recall invisibly. | Blocking recall measured against labels, printed on every scorecard. Measured, not eliminated. **residual** |
| P13 | Two genuinely identical transactions look like a duplicate. | Require a distinguishing field before suppressing; otherwise raise `E06`. Never auto-suppress on ambiguity. **closed** |
| P14 | Tolerance stacking — several small allowances compose into a large one. | Per-match tolerance budget consumed across tiers and recorded in the proof; exceeding it fails the match. **closed** |

### Ledger

| # | Problem | What stops it |
|---|---|---|
| P15 | Beancount v3 removed `bean-extract`/`bean-identify` from core and split out `beangulp`/`beanquery`. | Pin versions; write importers as scripts against the beangulp API. **closed** |
| P16 | Sub-paisa rounding leaves entries that don't balance. | Explicit rounding account with a policy threshold; above it is `E03`, not a silent plug. **closed** |
| P17 | FX booking — Beancount cost-basis semantics are easy to get subtly wrong. | Single functional currency (INR) in v1, FX as explicit conversion account. Multi-currency deferred with the limitation stated. **deferred** |
| P18 | Post-period chargebacks force reopening a closed period. | `E07` books to a disputes reserve by policy; reopening is a human decision. **closed** |

### Model edge

| # | Problem | What stops it |
|---|---|---|
| P19 | **An induced rule overfits** — right on history, wrong on future data. | Regression gate blocks promotion on any broken historical match; rules versioned, revocable, each carrying its justifying resolution. **residual — a gate is not a guarantee; needs post-promotion monitoring** |
| P20 | Triage classification non-deterministic run to run. | Structured outputs with the taxonomy as a closed enum; classification never affects a posting, only reading order. **bounded** |
| P21 | Truncated output — Opus 5 thinks by default and `max_tokens` caps thinking + response together. | Generous `max_tokens`; assert `stop_reason != "max_tokens"` on every call and fail loudly. **closed** |
| P22 | p99 latency on a novel source — synthesis costs a round trip. | Cache after first use; report p50 and p99 separately rather than hiding behind an average. **disclosed** |

### Evaluation and delivery

| # | Problem | What stops it |
|---|---|---|
| P23 | **Teaching to the test.** Generator drifts toward emitting exactly what the engine handles; score rises while capability doesn't. | Adversarial set authored at P0 before the engine exists; generator and engine never edited in the same commit. **residual — same team wrote both, and we should say so** |
| P24 | Metric gaming — headline match rate rises because tolerances were loosened. | False-match rate and proof-tier breakdown reported alongside, always. A rate without its tier split is not a result. **closed** |
| P25 | **Live model calls fail on stage** — rate limit, refusal, network. | Record the full run to a replay tape; demo from tape with live as fallback, and say which is running. Pre-warm the prompt cache. **closed** |
| P26 | Multi-tenant leakage between profiles or workspaces. | Scope on every query, enforced at the repository layer; a test asserting tenant A cannot read tenant B's proofs. **closed** |

**The four we do not fully close:** `P3` adapter tail errors, `P10` unproven subset uniqueness, `P19` rule overfit, `P23` generator/engine co-authorship. Each has a mitigation that reduces but does not eliminate the risk. They belong on the scorecard and in the talk track — a system whose pitch is honest verification cannot quietly round its own residuals to zero.

---

## 4. Decisions this plan assumes

| Decision | Taken as | Reversible? |
|---|---|---|
| Ledger substrate | Beancount v3, embedded | Yes — Postgres mirror is a P1 refactor if assertions prove awkward |
| Primary loop | Gateway settlement | Yes — GSTR-2B is P10, shares the kernel |
| qm adoption | Harvest patterns; Python-only v1 | Yes — adopting the TS core stays open, at the cost of the seam |
| Adapter authoring | Declarative spec, no codegen | **No** — the whole security argument rests on it |
| Public contracts | Semver'd from P1 | **No** — that is what makes them contracts |

If either irreversible looks wrong, that's the conversation to have before P0 rather than after P7.

---

## Sources new to this document

[RestrictedPython and LLM sandboxing limits](https://apxml.com/courses/building-advanced-llm-agent-tools/chapter-5-advanced-tool-functionality/code-execution-tools) · [SandboxEval (arXiv 2504.00018)](https://arxiv.org/pdf/2504.00018) · [STELP — secure transpilation of LLM-generated programs (arXiv 2601.05467)](https://arxiv.org/pdf/2601.05467) · [Sysdig — prompt injection guide 2026](https://www.sysdig.com/learn-cloud-native/prompt-injection) · [Untrusted content masking for web agents (arXiv 2607.05277)](https://arxiv.org/pdf/2607.05277) · [Beancount v3 — what's new](https://beancount.io/blog/2025/06/06/whats-new-in-beancount-v3) · [Splink](https://github.com/moj-analytical-services/splink) · [OR-Tools — enumerate all solutions](https://github.com/google/or-tools/discussions/3347) · [CP-SAT Primer](https://d-krupke.github.io/cpsat-primer/) · [FastMCP — tools](https://gofastmcp.com/servers/tools) · [FastMCP vs FastAPI-MCP vs Python SDK](https://mcp.directory/blog/fastmcp-vs-fastapi-mcp-vs-python-sdk-2026)
