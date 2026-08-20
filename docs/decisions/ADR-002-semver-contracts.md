# ADR-002 — Contracts are semver'd public objects from P1

Date: 2026-08-20 · Status: accepted
Reversible: **no** — that is what makes them contracts.

## Context

The system is meant to be a substrate other software builds on, not just an application. The MCP
ecosystem's open problem is that the tool_call -> tool_result cycle runs on an honor system, and
what financial and multi-tenant work needs is an audit trail the server cannot forge. Our answer is
the proof object: a caller re-derives the arithmetic instead of trusting us.

That only holds if the objects are stable. A proof whose shape drifts is not independently
checkable — the verifier a caller wrote last month stops working.

## Decision

`src/recon/contracts/` — `Record`, `Proof`, `Exception`, `Rule`, `AdapterSpec` — is a public,
semver'd surface from phase P1. Changing a field is a breaking change with a version bump, not an
edit. `verify_proof` is exposed as a stateless public call anyone can run.

## Consequences

Easy: external callers, portable artifacts, and independent verification all become possible.
The compoundability claim stops being aspirational.

Hard: the cost is paid at the start rather than the end. Getting a field wrong at P1 means carrying
it or shipping a major version. Contract design deserves more care than the rest of P1 combined.

## Alternatives rejected

- **Stabilize contracts later, once the engine settles** — the usual and easier path, but every
  caller written before stabilization breaks, which is precisely the trust we are trying to sell.
- **Version only the proof object** — a proof references `Record` fields; versioning one without
  the other leaves the guarantee half-made.
