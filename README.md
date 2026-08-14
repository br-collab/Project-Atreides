# Project Atreides — AI-assisted multi-asset settlement governance, with custodial routing

Atreides is a **governance layer for multi-asset settlement**. It sits above the
systems that actually move securities and money, governs the decision behind each
operation, selects the settlement path from an approved registry, and records the
whole thing as one replayable decision-of-record.

**Multi-asset** is a scope claim the code carries, not a slogan. Six securities
rails (`FICC_GSD_DVP`, `FICC_GCF_REPO`, `FICC_SPONSORED_DVP`, `FEDWIRE_SECURITIES`,
`FEDWIRE_FUNDS`, `SWIFT_MT202`), nine cash rails (Fedwire, CHIPS, FedNow,
NSS/DTC-NSCC, FICC GSD funds-only, correspondent, tokenized deposit, regulated
stablecoin, and a permanently reserved wholesale-tokenized placeholder), and three
settlement kinds (DvP, mark-to-market margin call, end-of-day net funding). Every
cash rail carries an explicit **finality class** — `GROSS_FINAL`, `DEFERRED_NET`,
`LEDGER_FINAL`, or `CORRESPONDENT_DEPENDENT` — because a rail choice that does not
state when the money becomes irrevocable has not actually been made.

A fifth class, `DETERMINATION_DEPENDENT`, belongs to the **obligation** rather than
to any rail, and no rail maps to it. It exists for contingent-payout instruments —
event contracts are the clearest case — where the cash leg is irrevocable on its
rail's own terms while the venue retains authority to cancel the contract and
return the funds. A decision record carries two finality classes where this
applies, because the money can be final while the entitlement to it is not. How
long a determined outcome stays qualified is the venue's disclosure, never this
framework's judgment: where a venue publishes a contest window the position leaves
the qualified state when that window elapses, and where it publishes none the
position stays qualified indefinitely and the record says so rather than converting
an unbounded window into a finality timestamp. See
`atreides/rails/determination.py`.

**Custodial routing** is a first-class dimension, not a configuration flag. Path
selection runs across seven doctrine-defined dimensions, and Dimension 4 is
*depository membership versus sub-custodian intermediation* — weighed on operational
efficiency, counterparty-risk concentration, jurisdictional compliance, and cost.
The other six cover multi-currency rail routing, correspondent-bank coordination,
the cross-border FX leg, large-value payment-system selection at material magnitude,
Federal Reserve account operations, and cash sweep destination.

**AI-assisted, stated precisely.** Tier 1 agents are deterministic. Tier 2 agents
have bounded autonomy over a **pre-declared approved-path registry** — 22 default
paths, each carrying its eligible ISO 4217 currencies, ISO 3166-1 jurisdictions, and
the doctrine subsection that justifies its inclusion. The agent enumerates from the
registry; **it never constructs a path at decision time.** An empty match does not
become improvisation — it becomes an `EscalationRequired` with
`failed_guardrail = APPROVED_PATHS_ONLY`. There is no adaptive tier in the custody
doctrine, and nothing here updates its own decision function from experience. That
is what makes any decision deterministically replayable years later, and what keeps
SR 11-7 ongoing-monitoring obligations tractable.

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

**1,024 tests · 99% coverage · MIT licensed.**

---

## The problem this addresses

Clearing and settlement portals are excellent at execution and silent on
governance. They show what is true and let an entitled participant act.
They do not record *why* a participant chose an action, *whose* authority
approved it, whether magnitude required additional authority, or produce a
regulator-replayable decision traced to the originating event.

That gap is the product.

The gap is widest on the **cash leg**, which is why the deepest implementation is
there. Most post-trade tooling governs the securities side and treats the money as a
consequence. A settlement has two legs; governing one and defaulting the other is a
half-governed settlement. So the cash leg is where this framework goes deepest —
funding feasibility, rail selection with finality, ISO 20022 emission — but it is
the **centre of gravity of a multi-asset layer, not its boundary.** The securities
leg, the FX leg, the custodial decision, and the cash leg all run the same gates and
land in the same decision-of-record.

---

## Where to start reading

**[`docs/CASH-LEG-WALKTHROUGH.md`](docs/CASH-LEG-WALKTHROUGH.md)** follows a
single USD settlement from tasking to instruction package, stopping at every
module and naming the doctrine each decision traces to. If you are picking
this up cold, start there — it is written for someone who knows settlement
operations and wants to see whether the code earns its claims.

Three **scenario write-ups** sit alongside it, each documenting one governance decision, the operator judgment it encodes, and the consequence of the alternative:

- **[`docs/SCENARIO-FUNDING-DISPOSITION.md`](docs/SCENARIO-FUNDING-DISPOSITION.md)** - why a queued payment is not a failed payment, and the six-disposition answer to "can this leg settle at all."
- **[`docs/SCENARIO-NET-OBLIGATION-MISMATCH.md`](docs/SCENARIO-NET-OBLIGATION-MISMATCH.md)** - the reconciliation control that holds rather than choosing when the firm's obligation and the CCP's published figure disagree.
- **[`docs/SCENARIO-DSOR-LINEAGE-MISMATCH.md`](docs/SCENARIO-DSOR-LINEAGE-MISMATCH.md)** - fail-safe, not fail-open: what happens when the governance record itself is the thing that is wrong.

---

## See it running

**[aureon-production.up.railway.app/cockpit](https://aureon-production.up.railway.app/cockpit)**
— the Settlement & Custody Console. Custody is the console; it has three
elements.

| Element | What it shows |
| --- | --- |
| **Pipeline** | One custody operation through seven governance gates to an append-only decision-of-record. It stops at the first gate that holds — the agent escalates, it never deviates. Representative flow, synthetic inputs, replayed in the browser. |
| **Breaks Workbench** | The exception surface. Where a held gate lands: symptom traced to proximate cause traced to originating event, with an action trail that is appended, never overwritten. |
| **Cash Leg** | Funding feasibility → rail selection with an explicit finality class → an ISO 20022 `pacs.009.001.13` package emitted against the published schemas. Computed **server-side per request** by this package at `/api/cashleg/*` — not a scripted animation. |

The securities leg and the cash leg both run the Pipeline's gates; the Cash
Leg tab is where the money side is resolved to a rail, a finality class, and
a message. Breaks Workbench is orthogonal to both — either leg feeds it.

The console is served from the deployment repository and imports this one as
a pinned dependency. It is deliberately not vendored here: per `AUR-ADD-006`
the relationship between the two repositories is a dependency, not a copy,
and a second copy of the console is the exact duplication that determination
exists to eliminate.

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

## Asset-class roadmap

The contracts layer is asset-class agnostic and rails are pluggable — a new
rail is a doctrine-plus-fixtures exercise, not an architecture change. The
implemented depth today is the U.S. Treasury / FICC complex and the cash leg.
The build order from here is chosen so that each rail forces the
decision-of-record to prove a different finality class the doctrine already
names:

| Rail | Finality class exercised | Venue complex | Status |
| --- | --- | --- | --- |
| U.S. Treasury / FICC | GROSS_FINAL — queues, WILL_QUEUE | FICC GSD, Fedwire Securities | **Built** |
| Equities | DEFERRED_NET — finality at end-of-day netting | Continuous net settlement, central depository | **Netting, fails and corporate-action overlay built**; market profiles unpopulated |
| Digital assets | LEDGER_FINAL — no queue; atomic DvP | Tokenized DvP; DTCC Tokenization Service-aware | Next build |
| Credit | Gross / deferred hybrid; TRACE reporting obligation | DTC / NSCC | Next build |
| FX | CORRESPONDENT_DEPENDENT — PvP; finality not directly observable | CLS, correspondent network | Following build |
| Event contracts | DETERMINATION_DEPENDENT — obligation-level; rail finality holds, entitlement is revocable | DCM-listed event contract venues | Contracts and gate branches built; venue profiles unpopulated |

The order is the finality taxonomy walked end to end. Status follows the same
convention as the rest of this document: a rail is Built when its gates,
contracts, and negative-path tests exist — not when a diagram does.

---

## Where this lands against the DTCC settlement transformation calendar

Context for anyone evaluating relevance rather than architecture. DTCC's published
[Settlement Transformation client roadmap](https://www.dtcc.com/-/media/Files/Downloads/Transformation/Settlement-Transformation-Client-Roadmap.pdf)
puts the participant-side work on dates:

| Date | Milestone |
| --- | --- |
| 21 Jan 2026 | PSE connectivity testing begins |
| 4 Mar 2026 | ISO 20022 Test Facility available — Deliver Orders, Payment Orders |
| 6 Jul 2026 | Production connectivity testing; ISO input/output early adoption begins |
| **30 Sep 2026** | **UAT / functional testing available in PSE**; reporting files available |
| 13 Nov 2026 | Production availability — Settlement Transaction Manager |
| Q3 2027 | Modernized Inventory Management go-live; legacy interfaces decommissioned |

PSE is DTCC's participant test environment — in their words, a testing environment
that facilitates user acceptance testing without impact on live activity.

**What this framework can plausibly contribute to that window.** Two things, stated
narrowly because the honest claim is narrow.

*Pre-submission conformance.* The emit path is validated in CI against the published
XSDs, which catches a class of defect that otherwise surfaces as a depository
rejection and costs a test cycle. Two real examples from this build: a timezone
offset emitted as `+0000` where `xs:dateTime` requires `+00:00`, and a monetary
amount normalised from `1000000.00` to `1E+6`. Both look correct in a unit test.
Both fail at a venue.

*Negative-path test generation.* Testing programmes are chronically thin on failure
paths because constructing a failure deliberately is harder than constructing a
success. The gate layer enumerates its own failure space — six funding dispositions
crossed with CATO-F's eight ordered checks, plus clearing-fund, net-obligation, and
lineage gates — so a negative test matrix can be derived from the decision space
rather than hand-written. The highest-value case in that set is `WILL_QUEUE`: a
queued gross-final instruction is **not** a failure, and a system that classifies it
as one and re-issues has created an irreversible duplicate payment.

**What it cannot contribute, and this is the more important half.** It cannot execute
a test cycle, because it does not submit — it prepares and adjudicates; the entitled
member transmits. It has never parsed a real depository readback, so it does nothing
for the inbound half of testing. And whether `pacs.009.001.13` is even the right
message against DTC's Payment Order mapping is precisely what sits behind the
participant-access documentation named above. That is an open question, recorded as
one rather than assumed away.

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
