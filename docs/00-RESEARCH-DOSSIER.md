# Track 04 — AI Finance Controller
## Research dossier: problem space, solution space, and proposed architecture

Date: 2026-08-20 · Status: pre-build, no code committed yet
Code graphs: `repos/securo/graphify-out/`, `repos/qm/graphify-out/`, merged `graphify-out/graph.json`

---

## 0. Verdict up front

Three findings drive everything below.

**1. The brief mislabels one of the two baselines.** `securo-finance/securo` is not "the fintech backbone." It is a self-hosted **personal finance manager** — the Actual Budget / Firefly III category. Its own source comments say it copied its matching thresholds from "what Actual and Sure use." It has no double-entry ledger, no journal, no AR/AP subledger, no invoices, no settlement. Its entire object graph hangs off a single `Transaction` node. That does not disqualify it — it has genuinely valuable parts — but building the books on it would be building on sand.

**2. `yc-software/qm` is the real asset, and it is better than the brief suggests.** It is a multi-tenant, audited, approval-gated, harness-agnostic agent substrate with **deterministic replay**. Replay is exactly the primitive a measured-accuracy track needs and almost nobody has.

**3. The architecture the track implies is backwards, and getting it right is the whole differentiator.** "Agentic reconciliation" suggests an LLM doing the matching. The evidence says an LLM must never do the matching. Top models drop from 95.6% accuracy on simple lookups to near 0% on multivariate calculations; multi-agent systems hit ~88% on financial *extraction* but ~52% on native numeric *calculation*. The correct shape is **a deterministic core that decides and proves, with the LLM confined to the edges** — parsing mess in, triaging exceptions out, and inducing rules that make the deterministic core smarter over time.

That third point is also what the track is really testing. The brief's own framing — *"verification capacity, not generation speed, is the bottleneck"* — is the answer, not just the motivation. Build the verifier, not the generator.

---

## 1. What the code graphs showed

Both repos were AST-extracted with graphify (no LLM cost, 92% EXTRACTED edges on securo).

| | securo | qm |
|---|---|---|
| Nodes / edges | 9,060 / 29,815 | 11,173 / 33,524 |
| Communities | 349 | 336 |
| Corpus | 632 code files (429 `.py`, 123 `.tsx`, 59 `.ts`) | 1,118 `.ts` + 115 `.md` |
| Top god node | `Transaction` (deg 437), `User` (481), `Account` (359) | `scopeId` (deg 596), `buildApp()` (360) |

### securo — what the graph reveals

The god-node ranking is the diagnosis. `User` → `Transaction` → `Account` → `WorkspaceContext` → `Asset` → `Category` → `BankConnection`. There is **no `Journal`, `Entry`, `Posting`, or `Ledger` node anywhere in `app/models/`**. `transaction.type == "debit"|"credit"` is a *direction flag on a single row*, not a double-entry pair. This is single-entry bookkeeping.

The matching surface, read directly:

- **`transfer_detection_service.py` (142 lines)** — the closest thing to a reconciler. Algorithm: exact absolute amount equality → different account → date within ±2 days → greedy closest-date-first, one pair per transaction. Strictly 1:1, exact-amount only. No fuzzy amount, no fee tolerance, no FX, no N:M.
- **`recurring_match_service.py` (201 lines)** — exact amount + frequency-aware date window + token-overlap similarity ≥ 0.6. Its own docstring concedes the limit: *"softer/variable-amount matching is intentionally left for a later suggestion-based pass."*
- **`import_service.py` (892 lines)** — OFX/QIF/CAMT/CSV parsing, encoding fallbacks, dedup hashing, bank-specific junk-row filters (e.g. Banco do Brasil balance rows posted as transactions). **This is the genuinely reusable asset.**
- **`rule_engine.py` (193 lines)** — deterministic conditions/actions. Good shape to copy.
- **`mcp_server/tools/`** — 14 tool modules including `proposals.py`, i.e. a human-in-the-loop propose-then-confirm pattern already exists.
- **`app/agents/`** — executor, MCP client, provider adapters (OpenAI / Anthropic / Ollama).

### qm — what the graph reveals

`scopeId` at degree 596 is the architecture in one number: **everything is scope-partitioned**. Per-person and per-room isolation is not bolted on, it is the spine.

Notable subsystems the graph surfaced:

- `src/harness/` — `claude-harness`, `codex-harness`, `opencode-harness`, `pi-harness`, `mock-harness`, plus `harness-router`, **`replay.ts`**, **`tape-fold.ts`**. Model-agnostic *and* replayable.
- `src/tools/primitives.ts` (1,216 lines) — a small fixed tool surface where `NeedsApproval` and `CommandDenied` are **first-class error types**, not afterthoughts.
- `src/audit/`, `src/security/` (provenance labelling + content screening, three postures), `src/skills/` (sync engine, packs, collision handling), `src/monitors/`, `src/triggers/`, crons.

### The honest reuse call

| Component | Call | Why |
|---|---|---|
| qm core (scopes, audit, approval gates, replay, skills, crons) | **Adopt** | Directly serves "measured accuracy" and "honest exception list." Replay makes runs reproducible. |
| securo `import_service.py` parsers | **Harvest** | 892 lines of real-world format pain already solved. Port, don't re-derive. |
| securo `rule_engine.py` shape | **Harvest** | Good deterministic condition/action model. |
| securo `transfer_detection_service.py` | **Publish as the baseline to beat** | Its exact-amount 1:1 greedy match is the honest "naive deterministic" control arm in our ablation. |
| securo data model / ledger | **Reject** | Single-entry. We need double-entry + AR/AP subledgers. |
| securo agent runtime | **Reject** | qm's is strictly better (approval gates, audit, replay, multi-harness). |

---

## 2. Problem space — where the pain actually is

Grounded in current practice, not vibes.

**The close is still measured in weeks.** Month-end close routinely stretches past a week; manual consolidation of 30+ entities pushes past 15 days. Controllers hired to produce insight spend the time re-keying data because a system cannot ingest a bank file in the right format.

**The unit economics of the bottleneck.** Bank-feed automation cuts a single bank reconciliation from ~47 minutes to *exception handling only*. That is the whole thesis in one statistic: **the matched records were never the cost. The exceptions are the cost.** A system that auto-matches 95% and hands back an unranked pile of 5% has moved the work, not removed it.

**Why matching is genuinely hard (not a lookup):**
- Inconsistent formats across banks; multiple rails (ACH, wire, card, RTP, FedNow, Zelle) in one operation
- Remittance detail missing or truncated — the reference that would make matching trivial is exactly what gets lost
- Partial payments, short-pays, overpayments, on-account cash
- Intercompany transactions that must net to zero across entities
- **Settlement is many-to-one by design.** A single gateway payout of £4,378.21 can represent 87 charges, 4 refunds, 3 chargebacks, 162 separate fees, and an FX adjustment. Gross never equals net. Refunds and chargebacks land days-to-months after the original sale.

**Adjacent loops with the same engine shape:**
- **GSTR-2B ↔ purchase register (India).** Monthly statutory match; an unmatched invoice is blocked Input Tax Credit, with ITC reversal and 18% interest exposure. Crisp ground truth, real money, and the exact same matching primitives.
- **13-week direct cash forecast.** Best-in-class targets ≥95% accuracy; tiered variance tolerance (<5% weeks 1–4, <10% weeks 5–8, <15% weeks 9–13). Note: forecast quality is downstream of AR/AP assumption quality — *"wide variance past week four usually traces back to weak AR or AP assumptions."* Forecasting without reconciliation is forecasting on garbage.

**Where the industry bar sits:** teams target 90%+ auto-match on routine streams; some report 97%. Confidence tiering is standard practice — auto-match at ~90%+ confidence, suggest at 72–90%, flag for review at 60–72%.

---

## 3. The binding constraint

This deserves its own section because it inverts the obvious design.

- LLMs are optimized for fluency, not rule-based precision. When a model "calculates revenue," it is producing a plausible narrative about numbers.
- Measured collapse: **95.6% on simple lookups → near 0% on multivariate calculations.**
- Extraction vs calculation split: **~88% on multi-agent financial extraction, ~52% on native numeric calculation.**
- The failure is silent. Textual explanations stay coherent while the numbers are wrong, which manufactures false confidence.
- FinBalance (710 records, 8 industries, 23 inconsistency codes) found ≤46% exact balance-sheet accuracy across six frontier models, and a **26–41pp gap between what models *reported* and what replaying their own journal entries actually produced.** Models contradict themselves and don't notice.
- DABStep (450+ tasks over real payments-analytics data): best agent **14.55% on the hardest tier.**
- Finance Agent Benchmark: best model (o3) **46.8%** at $3.79/query.

**Design consequence:** the agent may propose, parse, classify, rank, and explain. It may not decide a match and it may not compute a number that anyone relies on. Every match must close arithmetically under a deterministic checker, and the proof must be attached to the match.

This is also the answer to "what's the moat in a hackathon." Everyone will demo an LLM that reconciles. The differentiated thing is a system that **refuses to accept an unverified match** and can prove its own match rate.

---

## 4. Solution space survey

### Matching & entity resolution
- **Splink** (MoJ, MIT) — Fellegi–Sunter probabilistic record linkage, DuckDB/Spark/Athena backends, explainable match weights, scales to 100M+. Best fit for the fuzzy dimensions (counterparty name, reference string). Explainability matters: an auditor can read a Fellegi–Sunter weight.
- **Zingg** (active-learning ER, Spark), **dedupe** (human-in-the-loop), **Python Record Linkage Toolkit** (prototyping). Splink is the strongest default.
- Subset-sum / constraint solving for the N:M settlement case — this is an OR problem, not an ML problem. `python-constraint`, OR-Tools, or a bounded DP with tolerance.

### Ledger
- **Beancount** (Python, double-entry, plain text, balance assertions, `bean-check`) — the balance-assertion mechanic *is* a reconciliation verifier, and it is already battle-tested. `rustledger` is a Beancount-compatible faster reimplementation. **Strong candidate for the canonical ledger layer**, either embedded or as the schema we mirror in Postgres.
- hledger — better CSV rule files, weaker Python integration.

### Retrieval
- **PageIndex** (Vectify) — vectorless, tree-structured document index with LLM reasoning over the tree. **98.7% on FinanceBench.** Purpose-built for SEC filings, contracts, long financial documents. Correct tool for the *document* side: what does the merchant agreement say the fee should be, what does the tax rule require.
- **GraphRAG** (Microsoft) — entity extraction → community detection → community summaries → graph-aware retrieval. Reported ~34% query-accuracy lift when entity resolution is done properly. Correct for the *counterparty and netting-chain* side: alias resolution, intercompany chains, "who is this payer really."
- Do **not** use either for numeric matching. Vector RAG in particular is weak on tables and numbers.
- **Agentic GraphRAG** (arXiv 2605.18770) — agents navigating a KG built from financial documents, explicitly aimed at auditability. Notes real limitations: scalability of large KGs, dependence on extraction quality, interpretability/efficiency trade-off.

### Benchmarks & eval
- **FinBalance** (arXiv 2606.15949) — multi-document accounting reconciliation, 710 records, deterministic scenario generator, 23 inconsistency codes, `BS_exact` vs `BS_recon` metrics. **Generator, eval harness, ablation runner, and bootstrap analyzer released Apache-2.0.** Directly reusable scaffolding for our harness.
- **DABStep** (arXiv 2506.23719) — 450+ multi-step data-analysis tasks over real payments-platform data, factoid answers with automatic checking.
- **FinanceBench** (10,231 questions, evidence-string grounded), **BizFinBench.v2** (28,860 questions, offline+online), **Finance Agent Benchmark**, **FinVerBench** (calibration and benchmark validity).
- **AMLworld / PaySim / AMLSim** — agent-based synthetic financial transaction generators with complete ground truth. The methodological point worth stealing: *synthetic beats real for evaluation because the labels are complete* — in real data, many true positives were never detected, so real-data "ground truth" is itself unreliable.

### Verification patterns (the 2026 consensus, confirmed)
Four verifier architectures in circulation: output scoring (LLM-as-judge), Reflexion loops, adversarial debate, and process verification. **For a numeric domain, none of these is the right primary verifier** — a symbolic checker is. LLM-as-judge is appropriate only for the narrative quality of an exception explanation, never for whether a match is correct.

---

## 5. Proposed architecture

**Name for the thesis: propose–verify–prove.** The LLM proposes. A deterministic engine verifies. The system emits a proof object with every decision.

```
┌─────────────────────────────────────────────────────────────────┐
│  L6  EVAL HARNESS   synthetic generator · ablation runner ·      │
│                     baselines · metrics · adversarial set        │
├─────────────────────────────────────────────────────────────────┤
│  L5  AGENT HARNESS (qm)  scopes · approval gates · audit ·       │
│                          replay · skills · crons                 │
├─────────────────────────────────────────────────────────────────┤
│  L4  LLM EDGE   (a) normalizer/extractor  (b) exception triage   │
│                 (c) rule induction        — proposals only       │
├─────────────────────────────────────────────────────────────────┤
│  L3  MATCH ENGINE (deterministic)  T0 exact · T1 tolerant ·      │
│                   T2 subset-sum N:M · T3 → exception queue       │
│                   every match emits a PROOF that closes to zero  │
├─────────────────────────────────────────────────────────────────┤
│  L2  CANDIDATE GEN  blocking keys · Splink probabilistic score   │
├─────────────────────────────────────────────────────────────────┤
│  L1  INGEST & NORMALIZE  OFX/QIF/CAMT/CSV (harvest securo) ·     │
│                          gateway settlement · invoice register   │
├─────────────────────────────────────────────────────────────────┤
│  L0  CANONICAL LEDGER  double-entry · balance assertions         │
└─────────────────────────────────────────────────────────────────┘
        side-car:  PageIndex (documents)   GraphRAG (counterparties)
```

### Why each layer is where it is

**L0 — Canonical double-entry ledger.** Beancount-shaped. Every accepted match writes a journal entry; every entry balances or the write is rejected. Balance assertions against bank statements are free verification. This is the thing securo does not have and cannot be retrofitted with cheaply.

**L1 — Ingest.** Port securo's parsers. Normalize into a canonical `Record`: `{id, date, amount: Decimal, currency, direction, counterparty_raw, reference_raw, source, doc_hash}`. `Decimal` everywhere — never float. `doc_hash` gives idempotent re-ingest.

**L2 — Candidate generation.** The throughput lever. Never compare N×M. Block on amount buckets, date windows, normalized reference keys, counterparty tokens. Splink scores the fuzzy dimensions. Report blocking recall as a first-class metric — a candidate generator that drops the true pair caps the whole system, and this failure is invisible unless measured.

**L3 — Deterministic match engine.** Tiered, each tier emitting a proof:
- **T0 exact** — amount + date + reference. Auto.
- **T1 tolerant** — amount within ε (fee/FX/rounding), date within window, normalized reference. Auto, with the tolerance used recorded in the proof.
- **T2 subset-sum** — the settlement case. Find the subset of charges/refunds/fees that sums to the payout within tolerance. Bounded search with explicit ambiguity detection.
- **T3** — unmatched → exception queue.

**The proof object is the core artifact.** For every match: the record IDs on both sides, the arithmetic that closes to zero, the tolerance consumed, the rule or tier that fired, and the resulting journal entry. A match without a passing proof is not a match. This is what makes the reported match rate trustworthy rather than asserted.

**L4 — LLM edge, three jobs and no others.**
1. **Normalizer / extractor** — messy bank memos, remittance PDFs, unstructured advices → structured proposals. PageIndex for long documents. Output is candidate fields, never final numbers.
2. **Exception triage** — classify each unmatched item into the taxonomy, state a hypothesis, cite the evidence, rank by cash impact and age. Turns a pile into a worklist.
3. **Rule induction** — when a human resolves an exception, propose a durable deterministic rule so that class never recurs. This is the compounding loop: the system gets more deterministic over time, not more agentic.

**L5 — Harness (qm).** Scope isolation per entity/workspace. `NeedsApproval` on anything that writes a journal entry above a threshold or posts to a real system. Audit log per decision. Crons for scheduled close. Replay for reproducible benchmark runs. Skills as the packaging unit per loop.

**L6 — Eval harness.** Section 7.

---

## 6. Which loop to close

The track asks for **one** closed loop over a 50+ record batch. Recommendation: **payment-settlement reconciliation** — a three-way match across order/invoice register ↔ gateway settlement report ↔ bank statement.

Why this one:
- **It is natively many-to-one**, so it forces the T2 subset-sum path. This is precisely where securo's baseline fails outright and where a naive LLM demo also fails — a visible, defensible gap.
- **Ground truth is fully constructible** synthetically, with planted exceptions at known rates.
- **External validity** — DABStep is built on real payments-analytics data, so the domain is benchmark-legible.
- **The exception taxonomy is rich and real** — fee variance, FX, timing, chargebacks, partial capture.

Keep the engine schema-agnostic so **GSTR-2B ↔ purchase register** is a configuration, not a rewrite. Demoing the same engine closing a second, statutory loop is a strong generality claim — but only if the first loop is genuinely closed. One loop closed well beats two half-closed.

Deprioritize **forward cash forecasting** as the primary: accuracy cannot be honestly measured inside a hackathon window without waiting for the future, and its quality is downstream of reconciliation quality anyway. It is the right *phase 2*.

---

## 7. The eval harness — this is what wins the track

The bar is "throughput plus measured accuracy plus an honest exception list." That is a benchmarking deliverable, so build the benchmark first and the agent second.

**Synthetic generator** (FinBalance / AMLworld pattern): compose scenarios from business rules, then plant known exceptions at known rates. Complete labels by construction. Ship the generator so the numbers are reproducible.

**Metrics — report all of these, not just match rate:**

| Metric | Why it matters |
|---|---|
| Auto-match rate | The headline throughput number |
| Precision / recall on matches | Match rate alone is gameable by matching everything |
| **False-match rate** | **The metric that actually matters.** A wrong match is far worse than an unmatched item — it silently corrupts the books. Target near-zero and report it prominently. |
| Blocking recall | Caps the whole system; invisible unless measured |
| Exceptions surfaced ÷ exceptions planted | Tests the honesty of the exception list |
| Exception classification accuracy | Against the planted taxonomy label |
| Ambiguity detection rate | Did it flag genuinely ambiguous subset-sums instead of guessing? |
| Time-to-close, cost per record | Throughput and unit economics |

**Ablation arms** — run all four on the same batch:
1. securo `transfer_detection_service` (naive exact 1:1) — the published baseline
2. Deterministic engine only (T0–T2, no LLM)
3. LLM-only (agent does the matching) — expected to look good and be wrong, which is the point
4. Hybrid propose–verify–prove (the proposal)

Publishing arm 3's silent-error rate against arm 4 is the single most persuasive result available. It demonstrates the verification thesis with our own numbers rather than citing someone else's.

**Adversarial held-out set:** duplicate-with-different-reference, two valid subsets summing to the same payout, chargeback landing after period close, FX rate moved between capture and settlement, truncated reference, counterparty renamed mid-period.

---

## 8. Exception taxonomy

The "honest exception list" needs a fixed vocabulary, or the list is just prose. Proposed codes:

| Code | Class | Resolution owner |
|---|---|---|
| `E01` | Timing / in-transit | Auto-clears next period |
| `E02` | Fee variance vs contract | Needs contract lookup (PageIndex) |
| `E03` | FX rate / rounding difference | Auto within policy tolerance |
| `E04` | Partial payment / short-pay | Collections |
| `E05` | Overpayment / on-account | Cash application |
| `E06` | Duplicate | Auto-suppress with proof |
| `E07` | Chargeback / reversal, post-period | Accrual decision |
| `E08` | Missing remittance advice (unapplied cash) | Vendor follow-up |
| `E09` | **Netting ambiguity — multiple valid subsets** | **Must escalate, never guess** |
| `E10` | Reference corruption / truncation | Normalizer + rule induction |
| `E11` | Counterparty alias mismatch | Entity resolution (Splink / GraphRAG) |
| `E12` | Wrong entity / intercompany misposting | Intercompany netting |

`E09` deserves emphasis. When several subsets of invoices sum to the same payout, **there is no unique correct answer**. A system that picks one is fabricating. Detecting and reporting ambiguity is a correctness feature, and most demos will silently guess here.

---

## 9. Component inventory

| # | Component | Build / Adopt / Harvest | Source |
|---|---|---|---|
| 1 | Double-entry ledger + balance assertions | Adopt / mirror | Beancount |
| 2 | OFX/QIF/CAMT/CSV parsers | Harvest | securo `import_service.py` |
| 3 | Gateway settlement + invoice register ingest | Build | — |
| 4 | Canonical `Record` normalizer (Decimal, doc_hash) | Build | — |
| 5 | Blocking / candidate generation | Build | — |
| 6 | Probabilistic scorer (counterparty, reference) | Adopt | Splink |
| 7 | Tiered match engine T0–T3 | **Build — core IP** | — |
| 8 | Subset-sum solver + ambiguity detector | **Build — core IP** | OR-Tools / bounded DP |
| 9 | Proof object + verifier | **Build — core IP** | — |
| 10 | Rule engine (conditions/actions) | Harvest shape | securo `rule_engine.py` |
| 11 | Document retrieval (contracts, advices, tax rules) | Adopt | PageIndex |
| 12 | Counterparty / netting-chain graph | Adopt | GraphRAG + Splink ER |
| 13 | LLM normalizer/extractor | Build | — |
| 14 | LLM exception triage | Build | — |
| 15 | LLM rule induction | Build | — |
| 16 | Agent harness: scopes, approval, audit, replay | Adopt | qm |
| 17 | Synthetic generator + labels | Build (pattern from FinBalance/AMLworld) | — |
| 18 | Ablation runner + metrics | Build (scaffold from FinBalance, Apache-2.0) | — |
| 19 | Naive baseline arm | Harvest | securo `transfer_detection_service.py` |
| 20 | Adversarial held-out set | Build | — |

Items 7, 8, 9 are the differentiated core. Everything else is assembly.

---

## 10. Build order

1. **Synthetic generator + ground-truth labels.** Nothing can be measured before this exists.
2. **Canonical `Record` + double-entry ledger + proof object schema.**
3. **Deterministic engine T0/T1** and the securo baseline arm. First real number on the board.
4. **T2 subset-sum + ambiguity detection.** The hard, differentiated part.
5. **Metrics + ablation runner.** Lock the measurement before adding the LLM, so the LLM's contribution is measured, not assumed.
6. **LLM edge** — normalizer, then triage, then rule induction.
7. **qm harness integration** — scopes, approval gates, audit, replay.
8. **PageIndex / GraphRAG side-cars** if time allows. These are enhancements, not the spine.
9. **Second loop (GSTR-2B)** only if loop one is genuinely closed.

---

## 11. Open decisions

These change the build materially and are yours to make:

1. **Ledger substrate** — embed Beancount directly, or mirror its schema in Postgres? Beancount is faster to trust and gives balance assertions free; Postgres is easier to serve from an API and to scope per-tenant in qm.
2. **Domain** — settlement recon (recommended) vs GSTR-2B first. GSTR-2B has sharper real-world stakes and India relevance; settlement has better benchmark legibility and forces the harder N:M path.
3. **qm adoption depth** — full harness adoption (TypeScript core, deployment directory, real infra) vs harvesting its patterns into a lighter Python service. Full adoption is stronger but the core is a substantial system to stand up inside a hackathon.
4. **Language split** — securo's parsers and Beancount and Splink are Python; qm is TypeScript. Either accept a two-language system with a clean seam, or reimplement one side.

---

## Sources

Problem space: [Moveo — financial reconciliation & AI agents 2026](https://moveo.ai/blog/financial-reconciliation-ai-agents) · [Prophix — month-end close pain points](https://www.prophix.com/blog/how-to-overcome-common-pain-points-in-month-end-financial-close/) · [J.P. Morgan — month-end close & reconciliation](https://www.jpmorgan.com/insights/business-planning/month-end-close-process-and-reconciliation-tips) · [Numeric — month-end reconciliation](https://www.numeric.io/blog/month-end-reconciliation)

Settlement & standards: [Optimus — Stripe reconciliation guide](https://optimus.tech/blog/stripe-reconciliation-guide) · [Webgility — gateway settlement discrepancies](https://www.webgility.com/blog/payment-gateway-settlement-discrepancies) · [BNY — camt.054 deep dive](https://www.bny.com/content/dam/bnymellon/documents/pdf/iso-20022/learning-guide-module-9.pdf) · [Deutsche Bank — camt.05X overview](https://corporates.db.com/files/documents/in-focus/focus-topics/iso20022/camt-FactSheet-final-EN.pdf)

Tax-line matching: [WebLedger — GSTR-2B vs purchase register](https://webledger.in/gstr-2b-with-purchase-register-automatically/) · [FutureX — ITC mismatch](https://futurexsolutions.com/gstr-2b-reconciliation-itc-mismatch-fix/)

Cash forecasting: [Ripple Treasury — 13-week forecasting](https://treasury.ripple.com/posts/what-is-13-week-cash-flow-forecasting) · [Accordion — 13-week forecasting guide](https://www.accordion.com/our-insights/knowledge/13-week-cash-flow-forecasting-guide/)

LLM numeric limits: [Moveo — why LLMs struggle with math & structured data](https://moveo.ai/blog-new/why-llm-struggle) · [Forbes Tech Council — why LLMs fail at basic math](https://www.forbes.com/councils/forbestechcouncil/2026/02/26/why-the-llm-fail-at-basic-math-and-how-to-fix-it/) · [JurisTech — LLM hallucination benchmark for financial analysis](https://juristech.net/best-llm-tools-for-financial-analysis-2026/)

Benchmarks: [FinBalance (arXiv 2606.15949)](https://arxiv.org/abs/2606.15949) · [DABstep (arXiv 2506.23719)](https://arxiv.org/abs/2506.23719) · [Finance Agent Benchmark (arXiv 2508.00828)](https://arxiv.org/abs/2508.00828) · [BizFinBench.v2 (arXiv 2601.06401)](https://arxiv.org/abs/2601.06401) · [FinVerBench (arXiv 2605.29586)](https://arxiv.org/pdf/2605.29586) · [AMLworld — realistic synthetic financial transactions (arXiv 2306.16424)](https://arxiv.org/pdf/2306.16424)

Retrieval & graph: [PageIndex](https://pageindex.ai/blog/pageindex-intro) · [VectifyAI/PageIndex](https://github.com/VectifyAI/PageIndex) · [Microsoft — GraphRAG in financial services](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/unlocking-insights-graphrag--standard-rag-in-financial-services/4253311) · [Agentic GraphRAG (arXiv 2605.18770)](https://arxiv.org/pdf/2605.18770)

Entity resolution: [Splink](https://moj-analytical-services.github.io/splink/index.html) · [Awesome Entity Resolution](https://github.com/OlivierBinette/Awesome-Entity-Resolution) · [Tilores — Splink vs Zingg vs dedupe](https://tilores.io/content/best-open-source-entity-resolution-and-record-linkage-libraries-splink-zingg-dedupe-and-when-to-move-beyond-them/)

Ledger: [Beancount](https://beancount.github.io/) · [Plain Text Accounting](https://plaintextaccounting.org/) · [rustledger](https://github.com/rustledger/rustledger)

Matching practice: [Midday — automatic reconciliation engine](https://midday.ai/updates/automatic-reconciliation-engine/) · [Optimus — fuzzy matching in bank reconciliation](https://optimus.tech/blog/fuzzy-matching-algorithms-in-bank-reconciliation-when-exact-match-fails) · [Scry AI — reconciliation KPIs 2026](https://scryai.com/blog/account-reconciliation-metrics/)

Verification thesis: [Who Verifies the Agents? — NeurIPS 2026 workshop](https://verify-agents-workshop.github.io/) · [The AI verification bottleneck](https://antoniopagano.com/blog/ai-verification-bottleneck/) · [Verification is the new bottleneck](https://danielkeller.com/tech/verification-not-generation/)
