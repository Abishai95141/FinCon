# ADR-001 — Adapters are declarative specs; no generated code is executed

Date: 2026-08-20 · Status: accepted
Reversible: **no** — the entire security argument for generative intake rests on it.

## Context

The architecture requires absorbing novel file formats without configuration, which means a model
produces the thing that parses an unseen source. The obvious reading — the model writes Python that
we then execute over financial data — is remote code execution with a language model on the far end.

The standard mitigations do not hold at our scale of effort. RestrictedPython is documented as
"notoriously difficult to get right and often bypassed over time as new attack vectors are
discovered" and "generally insufficient on its own for truly untrusted code from an LLM."
Containers share the host kernel. Firecracker microVMs are the credible answer and are far more
infrastructure than this project can stand up.

## Decision

The model emits an **AdapterSpec**: a JSON document drawn from a closed vocabulary of readers,
field mappings, and parse verbs. A hand-written deterministic interpreter (~400 lines,
`src/recon/intake/spec.py` + `verbs.py`) executes it.

No `eval`, no `exec`, no `importlib`, no dynamic code from a model, anywhere in the codebase.
An unknown parse verb is a **spec validation error**, never an execution.

## Consequences

Easy: generative intake is safe by construction — there is nothing arbitrary to escape from.
Specs are diffable, reviewable, signable, and portable across tenants, which is what makes the
compounding-substrate argument work at all.

Hard: sources the spec vocabulary cannot express need a human-written adapter. In v1 that is the
accepted answer; sandboxed codegen for exotic formats is a v2 decision with real infrastructure
attached, and must not be slipped in under time pressure.

## Alternatives rejected

- **RestrictedPython / AST allowlisting** — a language-level sandbox that is bypassed as new
  attack vectors are found. Insufficient for genuinely untrusted generated code.
- **Container sandbox** — shares the host kernel; a permissive container running untrusted
  generated code is escapable.
- **Firecracker microVM** — correct, and disproportionate infrastructure for this build. Revisit
  only if v2 needs arbitrary codegen.
- **Human-written adapters only** — safe, but forfeits the flexibility claim that answers the
  central objection to the architecture.
