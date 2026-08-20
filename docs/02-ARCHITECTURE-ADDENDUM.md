# Open Intake, Verified Commit — architecture addendum

Date: 2026-08-20 · Amends [01-DECISION-SPEC.md](01-DECISION-SPEC.md) §3 and §7
Prompted by: the objection that a determinism claim costs us generalizability, and the requirement that this be a compoundable substrate for other AI.

---

## 1. The objection is correct

"Deterministic engine" reads as "rigid pipeline," and a rigid pipeline loses to a model that will at least *try* on a file it has never seen. That is a real failure mode and it's the one to avoid.

It isn't what the architecture requires. One word was doing two jobs. Separate them and the tension disappears.

| | **Authoring time** — unbounded, generative | **Run time** — deterministic, replayable |
|---|---|---|
| Novel file format | LLM **authors an adapter** | Adapter executes deterministically |
| Unknown columns | LLM **authors a field mapping** | Mapping executes deterministically |
| Foreign semantics | LLM **authors a semantic profile** | Profile executes deterministically |
| Resolved exception | LLM **authors a rule** | Rule executes deterministically |
| New domain | LLM **authors a loop profile** | Every artifact regression-tested before promotion |
| | No schema registry, no config, no engineer | Every commit carries provenance; runs replay byte-identically |

This is the established pattern in the schema-mapping literature, which generates mappings from heterogeneous JSON/CSV/XML/YAML with LLMs while *"ensuring scalability and reliability through deterministic execution of generated mapping rules."* LLMatch and SCHEMORA already do the authoring half; we supply the verification half.

**The deterministic surface is small.** It is not the pipeline. It is roughly 200 lines of arithmetic checking that a residual equals zero, plus executors for whatever the model authored. Everything upstream — recognizing, parsing, mapping, interpreting — is fully generative.

---

## 2. The generalization ladder

Nothing here is hardcoded.

| What varies | Absorbed by | Authored by | Verified by |
|---|---|---|---|
| **Format** — CSV, XLSX, OFX, QIF, CAMT, MT940, JSON, XML, PDF | Source adapter | LLM | Row conservation + control-total tie-out |
| **Schema** — column names, nesting, ordering, junk rows | Field mapping | LLM | Type/domain checks on every field |
| **Semantics** — what "valor" means, D/C conventions, sign flips, locale decimals | Semantic profile | LLM | Balance roll-forward: opening + Σ movements = closing |
| **Count of sources** — 2-way, 3-way, N-way | Kernel is N-ary by construction | Profile config | Residual across all N closes to zero |
| **Domain** — settlement, GST/ITC, payroll, intercompany, AR/AP | Loop profile | LLM from examples | Held-out replay against labelled batch |
| **Volume** — 50 rows or 5M | Blocking / candidate generation | — | Blocking recall as a first-class metric |
| **Tolerance policy** — fee bands, FX drift, rounding, date windows | Rule | LLM from resolutions | Regression test vs full match history |

A "loop" is not code. It is a **profile** — adapters, match keys, tolerance policy, exception taxonomy, posting rules. Settlement recon and GSTR-2B are two profiles over one kernel, and a profile can be authored from examples rather than implemented.

---

## 3. Ingestion proofs — how flexibility stays safe

Known failure modes of LLM-authored adapters are documented: hallucinated fields, and sensitivity to arrangement — *"rearranging rows or columns in a table can impact accuracy."* So we don't trust the adapter; we test what it produced.

Five checks, none of which need knowledge of format or domain:

| Check | Assertion |
|---|---|
| **Row conservation** | `rows_in_file = rows_parsed + rows_rejected`, every rejection carrying a reason. Silent row loss impossible. |
| **Control-total tie-out** | If the file states a total, parsed amounts must sum to it exactly. |
| **Balance roll-forward** | For statements: `opening + Σ movements = closing`. Catches sign errors, dropped rows and mis-mapped amount columns in one assertion. |
| **Type/domain validity** | Every date parses, every amount Decimal, every currency ISO-4217, every direction resolves. |
| **Idempotence** | Re-ingesting the same file changes nothing (`doc_hash`). |

**First-use approval.** The first run of a novel adapter shows the controller a sample of raw rows beside parsed output; one confirmation, then cached and trusted. Small tax on real novelty, zero tax on steady state.

**Adapter-fault detection.** A source that historically matches at 90% suddenly matching at 3% is a broken adapter, not a reconciliation failure. Quarantine the adapter rather than dumping thousands of spurious exceptions on a human.

**Where this is still not airtight.** These checks are necessary, not sufficient. A source with no control totals, no closing balance and no internal redundancy gives little to verify against — types and row counts and not much more. Such data is admitted and stamped `UNVERIFIED_INTAKE`, and matches built on it inherit a lower proof tier. We degrade honestly rather than refusing the file or pretending we checked it.

---

## 4. Proof has tiers — the system never refuses to move

This is the part that most directly answers the rigidity worry. Proof is a **provenance stamp**, not a binary gate.

| Tier | Meaning |
|---|---|
| **P0 ARITHMETIC** | Residual closes to zero from raw records. Machine-verifiable, re-derivable by a third party without trusting us. Default for clean matches. |
| **P1 RULE** | A promoted rule fired. Verifiable by replaying that rule at its pinned version; the rule passed regression before promotion. |
| **P2 ATTESTED** | A named human approved it. Accountable and audited. For judgement calls arithmetic cannot decide. |
| **P3 DECLARED** | Accepted with a stated gap — unverified intake, out-of-policy tolerance, a source with no redundancy. Permitted, visible, counted separately. |

A close can complete carrying P2 and P3 items. What it cannot do is carry them **undeclared**. The scorecard always breaks the headline down by tier: "94% matched" is never opaque — it is 81% P0, 9% P1, 3% P2, 1% P3.

**The rule is not "refuse what you can't prove." It is "never move silently."** That distinction is the whole difference between a rigid system and a trustworthy one.

---

## 5. The substrate

The MCP ecosystem has a stated open problem: how does an orchestrator verify an MCP server did what it claims? The `tool_call → tool_result` cycle runs on an **honor system** — and for anything touching financial data or multi-tenant environments, what's needed is *an audit trail the server itself cannot forge*.

**That is precisely what a proof object is.** A caller need not trust our match; they can re-derive the residual from raw records. We aren't just another financial MCP server — we're one whose results are independently checkable. That property is the reason to build on us rather than beside us.

### Four public surfaces

| Surface | For | Contract |
|---|---|---|
| **MCP server** | Any agent — theirs, ours, whatever they run next year | Every mutating tool returns a *proof* or a *proposal*, never a bare assertion |
| **HTTP + OpenAPI** | Non-agent callers, ERP integrations, scheduled jobs | Same kernel, same objects, semver'd |
| **Typed event stream** | Downstream systems reacting to close state | `MatchProven` · `MatchRejected` · `ExceptionRaised` · `RuleInduced` · `RulePromoted` · `AdapterAuthored` · `IntakeUnverified` · `CloseBlocked` |
| **Portable bundles** | Moving learned artifacts between tenants/orgs | Signed, versioned, **verify-on-import** |

### MCP tool surface

```
intake       propose_adapter(sample)      → AdapterProposal + intake proof
             ingest(source, adapter_id)   → RecordSet + IntakeProof

match        run_match(profile_id, run)   → MatchSet + Proof[] + Exception[]
             get_proof(match_id)          → Proof              (re-derivable)
             verify_proof(proof)          → bool               (stateless, callable by anyone)

tail         list_exceptions(run, rank)   → Exception[]
             explain_exception(id)        → hypothesis + cited evidence
             resolve_exception(id, call)  → Resolution         [NeedsApproval]

learn        propose_rule(resolution)     → RuleProposal + regression report
             promote_rule(rule_id)        → RuleVersion        [NeedsApproval]

commit       post_journal(run)            → Entry[] + BalanceAssertion   [NeedsApproval]

portability  export_bundle(scope)         → SignedBundle
             import_bundle(bundle)        → VerifyReport       (kept only if it verifies locally)
```

`[NeedsApproval]` = human gate, enforced by qm.

### What compounds

The app is not the asset. Four artifact classes are — each versioned, signed, portable:

- **Adapters** — format + schema + semantics for one source. A Razorpay settlement adapter authored once is useful to everyone on Razorpay.
- **Rules** — tolerances and resolutions learned from real exceptions.
- **Profiles** — a whole loop: sources, keys, taxonomy, postings.
- **Proof and exception history** — the signal everything else is learned from.

**Verify-on-import** makes sharing safe: an imported adapter re-runs its own intake proofs against the importing tenant's real data and is kept only if it passes. The network effect is real but gated — nobody inherits someone else's broken mapping.

---

## 6. What this changes about the build

**Added to v1:** adapter synthesis + first-use approval (this *is* the flexibility demo) · the five ingestion proofs · N-ary kernel instead of hardcoded three-way · profiles as data · proof tiers P0–P3 on the scorecard · MCP server with `verify_proof` as a stateless public call · typed event emission.

**Explicitly deferred:** portable bundles and cross-tenant import (designed for, contracts fixed, not built) · full OpenAPI beyond kernel routes · PageIndex and GraphRAG side-cars · the GSTR-2B profile.

### The demo grows a first act

1. **Flexibility.** Drop a settlement file in a format, schema and language the system has never seen. No config. It authors an adapter, ties out the control total, shows five raw-vs-parsed rows, ingests.
2. **Trust.** Run the match. Proofs on every row. One candidate rejected for failing re-derivation. One exception escalated as `E09` ambiguous rather than guessed.
3. **Compounding.** Resolve three, approve three induced rules, re-run on fresh data, show the lift attributed rule by rule.
4. **Substrate.** An external agent calls `run_match` over MCP and independently re-derives the returned proof without trusting us.

---

## 7. Honest costs of this decision

| Cost | Detail |
|---|---|
| **Bimodal latency** | A novel format costs a model round-trip to author and verify an adapter. Steady state hits cache. p50 good, p99 slow — show p99 rather than hide it. |
| **Adapters right on the sample, wrong on the tail** | Documented LLM sensitivity to row/column arrangement. Ingestion proofs catch most; roll-forward catches sign and mapping errors. Residual risk real and non-zero. |
| **Weak sources verify weakly** | No control total, no closing balance → little to check. Stamp `P3 DECLARED` and count separately rather than claiming a verification we didn't perform. |
| **More surface to build** | Kernel + synthesis + MCP + events is materially more than a three-way matcher. Mitigated by the deferral list, but real. |
| **Contracts bind early** | Publishing Proof, Record, Exception, Rule and Adapter as public semver'd objects makes later changes breaking. Worth it for compoundability; a commitment made at the start. |

**The one claim to keep refusing:** "feed it anything" is a design goal, not a measured result. What we can demonstrate is a specific set of unseen formats handled without configuration, plus an honest degradation path for sources we can't verify. Anything stronger is a promise the harness can't back.

---

## Sources new to this document

[Towards scalable schema mapping using LLMs (ACM)](https://dl.acm.org/doi/10.1145/3737412.3743490) · [LLMatch — unified schema matching framework (arXiv 2507.10897)](https://arxiv.org/abs/2507.10897) · [SCHEMORA — schema matching via multi-stage recommendation (arXiv 2507.14376)](https://arxiv.org/pdf/2507.14376) · [AI-assisted JSON schema creation and mapping (arXiv 2508.05192)](https://arxiv.org/html/2508.05192v2) · [Programming-language techniques for LLM code-generation semantic gaps (arXiv 2507.09135)](https://arxiv.org/pdf/2507.09135) · [The MCP server ecosystem in 2026](https://dev.to/sahil_kat/the-mcp-server-ecosystem-in-2026-integration-layer-for-ai-agents-2mln) · [Financial MCP servers compared](https://chartlibrary.io/blog/financial-mcp-servers-compared)
