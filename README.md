# Project Atreides — governance for the cash leg of settlement

Atreides is a **governance overlay for clearing and settlement**. It sits
above the systems that actually move securities and money, governs the
decision behind each operation, and records it as one replayable record.

It does not move anything itself. That constraint is the design.

> **Atreides prepares · governs · reconciles. The entitled member submits.**

The framework never holds a depository, CCP, or payment-system credential,
never submits a transaction, and never scrapes a portal. An outside
framework cannot interpose itself in a regulated member's submission — so
the seat this occupies is governance, not execution. The boundary is
enforced at the type layer rather than by convention: `InstructionPackage`
and `InstructionArtifact` both pin `is_submission` to `Literal[False]`,
which makes a submission object *unconstructible* rather than merely
discouraged.

**793 tests · 99% coverage · MIT licensed.**

---

## The problem this addresses

Clearing and settlement portals are excellent at execution and silent on
governance. They show what is true and let an entitled participant act.
They do not record *why* a participant chose an action, *whose* authority
approved it, whether magnitude required additional authority, or produce a
regulator-replayable decision traced to the originating event.

That gap is the product.

It is sharpest on the **cash leg**. Most post-trade tooling governs the
securities side and treats the money as a consequence. A settlement is two
legs; governing one and defaulting the other is a half-governed settlement.

---

## Where to start reading

**[`docs/CASH-LEG-WALKTHROUGH.md`](docs/CASH-LEG-WALKTHROUGH.md)** follows a
single USD settlement from tasking to instruction package, stopping at every
module and naming the doctrine each decision traces to. If you are picking
this up cold, start there — it is written for someone who knows settlement
operations and wants to see whether the code earns its claims.

---

## What is built

| Component | Module | What it does |
| --- | --- | --- |
| **Clearing Operator Cockpit** | `atreides/cockpit/` | The five-beat operator cycle: gather → validate → prepare → *(member submits)* → reconcile. Six capability primitives; no `submit` method exists. |
| **CATO-F** — cash settlement-rail gate | `atreides/rails/cato_f.py` | Deterministic PROCEED / HOLD / ESCALATE across Fedwire, CHIPS, FedNow, NSS, FICC/GSD, correspondent and tokenized rails. Emits a rail **and a finality class**. |
| **Intraday funding model** | `atreides/rails/funding_state.py` | Whether the leg can actually settle. Distinguishes *will queue* from *will fail* — the distinction that prevents duplicate payments. |
| **ISO 20022 emit path** | `atreides/messaging/` | Canonical settlement model → `pacs.009` + `head.001`, validated in CI against the **published ISO 20022 XSDs**. |
| **FIAT Operations Specialist** | `atreides/agents/tier2/` | Path selection across seven dimensions — rail routing, correspondent coordination, cross-border FX leg, depository vs sub-custodian, large-value payment system, Fed operations, cash sweep — under bounded-autonomy guardrails. |
| **Settlement Operations Analyst** | `atreides/agents/tier1/settlement_operations_analyst.py` | Deterministic FICC / U.S. Treasury settlement execution with write-through to the decision record. |
| **Settlement Investigation Analyst** | `atreides/agents/tier1/settlement_investigation_analyst.py` | Reconstructs a break as a provenance-cited timeline across ten evidence sources. Infers nothing — cause ranking is a separate, bounded layer. |
| **Typed custody contracts** | `atreides/contracts/` | Asset class, custody object, settlement method, failure mode, inherent safety, authority. |
| **Decision record (DSOR)** | `atreides/dsor/` | Append-only, DTG-stamped, deterministic replay. |

---

## Four properties worth checking against the code

**Fail-safe, not fail-open.** Where the gate is unavailable the answer is
HOLD. `absent_gate_decision()` is a named exported function so that "what
happens when governance did not run" is answered in one auditable place
rather than at every call site. The FIAT Operations Specialist refuses to
select a cash rail without a gate decision and returns an escalation under
`NO_SETTLEMENT_WITHOUT_LINEAGE`.

**A queued payment is not a failed payment.** On a gross-final rail an
unfunded instruction *queues* and settles when funding arrives. Classifying
that as a failure and re-issuing creates a duplicate payment — which, once
final, the settlement system cannot reverse. The funding model reports
`WILL_QUEUE` with the offset at which the shortfall clears, and
`is_failure` deliberately excludes it.

**Messages are validated against the standard, not against our opinion of
it.** `tests/fixtures/iso20022/` carries the published XSDs and the suite
validates emitted XML against them. On the first run this caught two
defects every hand-written assertion had passed: `strftime("%z")` emitting
`+0000` where `xs:dateTime` requires `+00:00`, and `Decimal.normalize()`
silently stripping cents from a settlement amount.

**Determinism.** Gates and agents make no network call, read no clock, and
hold no state. Same inputs, same decision, byte for byte — which is what
makes a decision replayable from its recorded inputs.

---

## What is *not* built, and why

Honesty about the edges is load-bearing in a framework whose product is
provable correctness.

- **Submission capability** — never. Permanent by design, not a roadmap item.
- **Depository message profiles.** The emit path is conformant to the
  **base** ISO 20022 standard. Venues constrain those schemas: which
  optional fields become mandatory, which code values are permitted, and
  crucially **which message variant applies**. The `sese` settlement
  triplet ships as both variant 001 and variant 002 and they are not
  interchangeable. Resolving that requires DTCC's *Settlement Client
  Interface ISO 20022 Mapping*, which is behind participant access.
  `DepositoryProfile` is the seam — adopting a venue profile is a fixture
  change, not a code change. `DTCC_SETTLEMENT_PENDING` and
  `FEDWIRE_PENDING` are stubs flagged `UNVERIFIED` rather than populated by
  inference; a guessed profile would look authoritative and be wrong.
- **Inbound ingest and reconciliation** — the `camt` and `pacs.002` readback
  direction. Needs a member forwarding settlement output.
- **Cause diagnosis.** Evidence assembly is built; ranking causes against a
  closed inventory is specified and not yet implemented.
- **Multi-party authority ceremonies** — specified, deliberately inactive
  under the current single-operator model.

---

## Install and run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q          # 793 passed
```

Requires Python ≥ 3.11. Runtime dependency: `pydantic>=2.6`. `lxml` is
test-only — XSD validation runs in CI, never in the request path.

```bash
ruff check atreides tests
mypy atreides
```

---

## Architecture conventions

- **Pydantic v2** for contract types. Runtime validation is required, not
  optional.
- **Strict typing.** mypy in strict mode; no `Any` without justification.
- **Doctrine traceability.** Every non-trivial validator names the doctrine
  section that justifies it.
- **No silent failures.** The framework fails loudly toward safe states,
  never quietly toward operational continuation.
- **Every validator has a positive and a negative test.**

---

## Doctrine

The implementation is a doctrine corpus rendered as code. Every module
traces to a written commitment; code that traces to nothing is suspect. The
governing documents ship in `doctrine/`:

- `AUR-CANONICAL-001-v1_6.md` — framework architecture, governance axioms,
  authority model.
- `AUR-CUSTODY-001-v1_0.md` — custody and settlement operational doctrine:
  asset-class universe, settlement-method taxonomy, failure-mode classes,
  inherent-safety architecture.
- `AUR-COCKPIT-001-v0_1.md` — the clearing operator surface and its
  cardinal boundary.

Cash-leg specifics — `AUR-CUSTODY-CASH-001`, the rail universe, finality
classes, the CATO-F specification and the ISO 20022 obligation — live in the
restricted doctrine repository. The walkthrough cites the relevant sections
inline so the code can be followed without it.

---

## License

MIT License — Copyright (c) 2026 Guillermo Ravelo. See [LICENSE](LICENSE).

*Guillermo "Bill" Ravelo · Columbia University M.S. Technology Management*
