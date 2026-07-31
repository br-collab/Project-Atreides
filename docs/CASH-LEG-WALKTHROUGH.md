# Following one cash leg through Atreides

**Audience:** someone who knows clearing and settlement operations and wants
to see whether this code earns its claims. No prior exposure to the codebase
assumed. Roughly twenty minutes end to end.

Every output below is produced by [`walkthrough_demo.py`](walkthrough_demo.py)
in this directory. Run it yourself:

```bash
pip install -e ".[dev]" && python docs/walkthrough_demo.py
```

---

## Read this before the code

Atreides governs a settlement decision. It does not execute one.

> **Atreides prepares · governs · reconciles. The entitled member submits.**

That is not modesty about scope — it is the constraint the whole design
serves. An outside framework cannot interpose itself in a regulated
member's submission to a depository, CCP, or payment system. So the
framework holds no credentials, opens no sessions, and has no submit path.

The boundary is enforced where it cannot be argued with. `InstructionPackage`
in the cockpit and `InstructionArtifact` in the messaging layer both pin
`is_submission` to `Literal[False]`. A submission object is not discouraged;
it is **unconstructible**. There is no `submit()` method anywhere in the
package, and no field anywhere holds a credential.

If you take one thing from this document, take that. Everything below is
downstream of it.

---

## The scenario

A USD 1,000,000 cash leg settling against a Treasury purchase. The member
clears through FICC and settles cash over a large-value rail. We follow the
decision — not the money.

---

## Stop 1 — Can this leg settle at all?

`atreides/rails/funding_state.py`

Rail selection answers *how* money moves. This answers *whether it can*, and
it is the check that most often decides whether a cash leg completes.

The member opens with 250,000, owes 1,000,000, and has a 900,000 FICC net
receipt landing 90 minutes after the settlement instant. Short at the
instant, covered inside the window.

```
disposition        : will_queue
shortfall          : 750000
clears at          : +5400s
is_failure         : False   <-- a queue is NOT a failure
```

**This is the distinction the module exists to make.** On a gross-final rail
an unfunded instruction *queues*; it settles when funding arrives. Classify
that as a failure, re-issue, and you have created a duplicate payment —
which, once final, the settlement system cannot reverse. Recovery depends on
counterparty cooperation or litigation.

So the model never returns a bare "unfunded." It returns `WILL_QUEUE` with
the offset at which the shortfall clears, and `is_failure` deliberately
excludes it. Operations people recognise this immediately; software usually
gets it wrong.

Finality drives the treatment, because the same shortfall means different
things by rail:

| Finality class | Short at the instant means |
| --- | --- |
| Gross-final (Fedwire, FedNow) | Queues; fails only if funding misses the window |
| Deferred-net (CHIPS, NSS, FICC/GSD) | Measured at end-of-day finality, not at instruction |
| Ledger-final (tokenized) | Fails — there is no queue on a ledger |
| Correspondent-dependent | `INDETERMINATE` — finality is not observable, so the model declines to assert it |

Two further properties worth noting. Projections use **committed** flows
only; an expected-but-uncommitted receivable is reported separately and
never counted toward fundedness. And the net-debit cap is measured at the
**intraday trough**, not the closing position — an account that dips five
million below the cap at 10am and recovers by 3pm has breached it.

---

## Stop 2 — Which rail, and how final?

`atreides/rails/cato_f.py`

CATO-F is the cash-leg settlement gate. Deterministic, no I/O, no clock —
scalars in, decision out, so any decision replays from its recorded inputs.

```
decision           : PROCEED
recommended_rail   : fedwire
finality_class     : GROSS_FINAL
rationale          : Operation is LVPS-material; gross-final rail preferred
                     over deferred-net (CASH-001 SV.C.2, SIV finality doctrine)
```

Eight checks run in a fixed order, and **the order is doctrine, not
optimisation**: systemic stress escalates; material magnitude holds; unfunded
holds; a risk-control breach holds; broad stress holds; no rail in the window
holds; unresolvable correspondent finality holds; otherwise proceed with a
rail from a deterministic ladder.

Same operation, three other conditions:

```
under stress (0.75): HOLD / BROAD_STRESS_HOLD
queued leg         : HOLD / UNFUNDED_AT_SETTLEMENT_INSTANT
gate missing       : HOLD  <-- never PROCEED
```

That last line matters more than the others. **Where the gate is unavailable,
the answer is HOLD.** `absent_gate_decision()` is a named exported function
precisely so that "what happens when governance did not run" is answered in
one auditable place rather than re-decided at each call site.

Note the second line: the queued leg **holds at the gate** even though it is
not a failure. Both facts are true and neither is redundant. It should not be
released now; it should also not be re-issued. Collapsing those two into one
boolean is how duplicate payments happen.

Two design points a settlement reader will look for. The gate emits a
**finality class** alongside the rail, because materiality should tighten as
reversibility falls — an irreversible operation warrants a lower trigger than
a reversible one of the same size. And `ports_wholesale` is always present in
the rail set as a reserved placeholder with status `not_yet_issued`, so when
wholesale tokenized infrastructure ships the rail-state shape does not
change; only a status field flips.

---

## Stop 3 — Onto the wire

`atreides/messaging/`

```
rail 'fedwire' -> SettlementMethod1Code 'CLRG'
message_definition : pacs.009.001.13
profile            : base-iso20022 (verified=True)
is_submission      : False
```

`SettlementMethod1Code` has exactly four values — `INDA`, `INGA`, `COVE`,
`CLRG` — and the gate's rail selection maps onto them. RTGS and netted
clearing systems settle through a clearing system; correspondent chains
settle on an agent's books. **The gate chooses a rail; the rail determines
how the settlement is expressed on the network.** That mapping is the join
between governance and the message.

Rails with no `pacs` expression **raise rather than default**:

```
tokenized_deposit -> rail 'tokenized_deposit' has no ISO 20022
                     credit-transfer expression; ...
ports_wholesale   -> rail 'ports_wholesale' has no ISO 20022
                     credit-transfer expression; ...
```

Defaulting those to `CLRG` would put an assertion on the wire that a clearing
system settled something it never touched.

The emitted document:

```xml
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pacs.009.001.13">
  <FICdtTrf>
    <GrpHdr>
      <MsgId>AUR20260803000117</MsgId>
      <CreDtTm>2026-08-03T14:30:00+00:00</CreDtTm>
      <NbOfTxs>1</NbOfTxs>
      <SttlmInf><SttlmMtd>CLRG</SttlmMtd></SttlmInf>
    </GrpHdr>
    <CdtTrfTxInf>
      <PmtId><EndToEndId>TSY-SETTL-000117</EndToEndId></PmtId>
      <IntrBkSttlmAmt Ccy="USD">1000000.00</IntrBkSttlmAmt>
      <Dbtr><FinInstnId><BICFI>CHASUS33</BICFI>…</FinInstnId></Dbtr>
      <Cdtr><FinInstnId><BICFI>BOFAUS3N</BICFI></FinInstnId></Cdtr>
    </CdtTrfTxInf>
  </FICdtTrf>
</Document>
```

### Why this is validated rather than asserted

`tests/fixtures/iso20022/` carries the **published ISO 20022 XSDs**, and the
suite validates emitted XML against them. That is not ceremony. On the first
run it caught two defects that every hand-written assertion had passed:

`strftime("%z")` emits `+0000`. `xs:dateTime` requires `+00:00` or `Z`. Any
depository would have rejected the message; no reviewer would have spotted it.

`Decimal.normalize()` turned `1000000.00` into `1E+6` — scientific notation
the schema rejects, and worse, **silently stripped the cents** from a
settlement amount.

Both produced XML that looked correct. Only the schema disagreed.

### The domain model is deliberately stricter than the schema

`FinancialInstitutionIdentification23` makes every identifier optional, so a
schema-valid message can identify nobody. The model requires a BICFI and
enforces the actual `BICFIDec2014Identifier` pattern. It also rejects naive
datetimes — a timestamp with no zone silently asserts whatever the emitter's
local zone happened to be, which is exactly the class of defect that survives
testing and fails in production.

---

## Stop 4 — Submission

There is no stop 4. The member submits, under their own credentials and
controls, through their own connection. Atreides' role here is zero, by
design and permanently.

What the framework hands over is a schema-valid artifact the member drops in
unchanged. **If the member has to edit it before submitting, that is a defect
in the emit path**, not a configuration step.

---

## Stop 5 — When it breaks

`atreides/agents/tier1/settlement_investigation_analyst.py`

Settlement failures are routine. The expensive part is not diagnosis — it is
gathering evidence across the decision record, the instruction, message
status, funding state, the rail calendar, and the counterparty.

The Investigation Analyst assembles that into a provenance-cited, ordered
timeline across ten evidence sources. It **infers nothing**: no cause, no
ranking, no hypothesis. Cause selection is a separate layer bounded by a
closed inventory, and keeping them apart is what lets the diagnostic
capability exist without an adaptive model making unbounded causal claims.

That boundary is structural, not stylistic. `EvidenceTimeline` pins
`contains_inference` to `Literal[False]`; there is no `cause`, `hypothesis`,
or `ranking` field anywhere in the module; and a test asserts none can appear.

Two behaviours worth knowing:

**A forgotten source escalates.** If nine of ten sources are supplied and the
tenth is neither observed nor declared as a gap, the agent manufactures an
`UNAVAILABLE` gap for it and escalates. A timeline that *looks* complete and
isn't is the thing that misleads a diagnosis.

**Escalations keep the evidence.** A gap never costs the operator the
timeline that was assembled — the escalation carries it.

---

## What is blocked, and precisely why

The emit path conforms to the **base** ISO 20022 standard. Venues constrain
those schemas, and the constraints are not guessable.

Concretely: the `sese` settlement triplet ships as **variant 001 and variant
002**. They are not interchangeable, and choosing wrong produces messages
that validate against the wrong schema and are rejected downstream. Which
applies is stated in DTCC's *Settlement Client Interface ISO 20022 Mapping*,
alongside *ISO 20022 Message Specification UAT V6* — both behind participant
access on the DTCC Learning Center.

So `DepositoryProfile` exists as the seam. Message identifiers, variant,
business service, venue-mandatory fields, and restricted code values are all
**profile data**, which makes adopting a venue profile a fixture change under
propose/approve discipline rather than a code change.

`DTCC_SETTLEMENT_PENDING` and `FEDWIRE_PENDING` are stubs flagged
`UNVERIFIED` rather than populated by inference. A profile filled in by
guesswork would look authoritative and be wrong — the worst possible artifact
in a framework whose product is provable correctness.

One dated note: the Fedwire ISO 20022 implementation center flags a
**November 2026 release**, which lands between now and the SEC Treasury
cash-clearing mandate date of 31 December 2026. Current-state formats are not
the ones to build against for go-live.

---

## Where to look next

| If you want to see | Read |
| --- | --- |
| The operator cycle and its boundary | `atreides/cockpit/clearing_cockpit.py` |
| Gate check order and the rail ladder | `atreides/rails/cato_f.py` §§ `evaluate`, `_recommend_rail` |
| Queue-versus-fail logic | `atreides/rails/funding_state.py` § `project_funding` |
| Schema conformance tests | `tests/messaging/test_emit.py` § `TestSchemaConformance` |
| Bounded path selection under guardrails | `atreides/agents/tier2/fiat_operations_specialist.py` |
| Append-only decision record | `atreides/dsor/store.py` |

```bash
pytest -q          # 793 passed
```

---

*Project Atreides · Guillermo "Bill" Ravelo · Columbia University M.S.
Technology Management*
