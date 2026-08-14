# Glossary

This is a control, not a reference.

`AUR-CUSTODY-MARGIN-001` and the standards posture it carries fix a vocabulary rule: **adopt the standard's language at the seam, and keep this framework's language inside the decision layer.** A glossary organised that way is the enforcement of that rule rather than a courtesy to the reader. Section 1 is what this framework consumes and does not get to redefine. Section 2 is what it invented and therefore owes an explanation for. Section 3 is what it refuses to say, and why - which is the section worth reading first, because a framework's refusals tell you more about what it actually claims than its features do.

Structures and fields are in [`DATA-DICTIONARY.md`](DATA-DICTIONARY.md).

---

## 1. Taken from the standard, at the seam

These terms are not this framework's to define. Where the meaning here differs from the standard's, the standard is right and this document is a bug.

### ISO 20022 messaging

| Term | Meaning | Where it enters |
| --- | --- | --- |
| `pacs.009.001.13` | Financial institution credit transfer. The cash-leg instruction. | Emitted by `messaging/emit.py` |
| `pacs.002.001.16` | Payment status report. The venue's answer. | Parsed by `messaging/readback.py` |
| `pacs.008.001.14` | Customer credit transfer. Held as a schema; not emitted. | Fixture only |
| `head.001.001.04` | Business application header. | Emitted alongside the document |
| `BizMsgIdr` | Business message identifier on the header. | Set from `message_id` |
| `MsgId` | Message identifier in a group header. | Both emit and readback |
| `EndToEndId` / `OrgnlEndToEndId` | The payer-assigned reference that survives the chain, and the venue's echo of it. | The readback match key |
| `OrgnlMsgId` | The original message identifier the status refers to. | The second readback key |
| `TxSts` / `GrpSts` | Transaction and group status codes. Externalised code sets. | Classified, never invented |
| `IntrBkSttlmAmt` | Interbank settlement amount, with a currency attribute. | Amount and currency mismatch checks |
| `SttlmMtd` | Settlement method: `INDA`, `INGA`, `COVE`, `CLRG`. The complete enumeration from the schema. | `SettlementMethod` |
| `BICFI` | Business identifier code, matched against `BICFIDec2014Identifier`. | `FinancialInstitution` |
| `Max35Text`, `ActiveCurrencyCode` | Schema types enforced in the domain model rather than at the depository. | `CashLegInstruction` |

The four XSDs in `tests/fixtures/iso20022/` are the published schemas, carrying their Standards Editor generation stamps. Tests validate emitted messages against them rather than against assertions written by hand.

### Settlement and clearing

| Term | Meaning |
| --- | --- |
| Novation | The clearing corporation becomes counterparty to both sides. After it, the original trade is no longer the settlement object. |
| Netting | Offsetting obligations into one position per security per member. |
| DvP / PvP | Delivery versus payment; payment versus payment. |
| Fail to deliver / fail to receive | The two sides of an unsettled obligation. Different remedies, so different dispositions here. |
| Buy-in / sell-out | Forced purchase or sale to close a fail. |
| Record date / ex-date | The dates that fix corporate-action entitlement. |
| Entitlement | What a holder is owed from a corporate action, independent of whether delivery occurred. |
| Net debit cap | The intraday debit ceiling under Federal Reserve Payment System Risk policy. |
| Locate | The Reg SHO requirement that a short sale have a borrow located before the sale. |

### Margin

| Term | Meaning |
| --- | --- |
| Initial margin / variation margin | Collateral against future exposure; collateral against realised mark-to-market. |
| Add-on | An increment for concentration, liquidity or wrong-way risk. Frequently judgment rather than model output, which is why this framework will not derive one. |
| Haircut | The discount applied to posted collateral. Recorded only with provenance. |
| Eligible collateral | What a venue will accept. Read from the venue, never inferred. |
| Margin responsiveness | A published, backward-looking measure of how fast margin moved against how fast the market moved. Consumed as disclosure, never as a forecast. |
| PFMI | The international principles for financial market infrastructures. Addressed to infrastructures and their supervisors. See section 3. |

---

## 2. This framework's own vocabulary

Invented here, and owed an explanation. Renaming any of these to sound standards-adjacent would borrow authority while losing the part that is actually new.

| Term | Meaning |
| --- | --- |
| **DSOR** | Decision system of record. Append-only, byte-for-byte replayable. One row per decision; a correction is a new row, never an update. |
| **Finality class** | When and how a movement becomes irrevocable. Four rail classes and one obligation class. |
| **`DETERMINATION_DEPENDENT`** | Obligation-level. The cash is final on its rail and the venue may still cancel the contract and return the funds. The money is final; the entitlement is not. |
| **Determinability regime** | How knowable a venue's margin figure is from outside it: fully collateralised, published-parameter, discretionary, undisclosed. A property of the venue, not of this framework. |
| **Revocation form** | Whether a venue's emergency authority preserves settlement (liquidation at an administered price) or reverses it (cancellation and return of funds). Only the second produces determination dependence. |
| **Qualified** | Determined, and still revocable. A qualified receipt is not free cash. |
| **Funding disposition** | What will happen to a cash leg on funding grounds. `WILL_QUEUE` is deliberately not `WILL_FAIL`. |
| **`FUNDED_QUALIFIED`** | Settlement completed against a revocable entitlement. |
| **Margin disposition** | What a break means for margin. Seven values, because the question has more than two materially different answers. |
| **`CALL_WINDOW_CLOSED`** | Exposure quantified and simultaneously uncollectable. The remedy is a position or hedging decision, not a call. |
| **Observability** | On what basis an assessment is held: observed, derived, unobservable. A separate axis from the assessment itself. |
| **Unsolicited readback** | A venue status for an instruction this framework never prepared. The detector for out-of-band submission. |
| **CNS disposition** | The outcome for one net position. `PARTIAL_ALLOCATION` is the ordinary case, not an exception path. |
| **Gate** | A deterministic checkpoint returning proceed, hold or escalate. Check order is doctrine, not optimisation. |
| **CATO-F** | The cash-leg rail gate. Cash-side twin of the securities-side gate, held in bit-for-bit parity with it. |
| **Approved-path registry** | The pre-declared set of settlement paths an agent may enumerate from. It never constructs a path at decision time; an empty match escalates rather than improvises. |
| **Failure-mode class** | `RA`, `RM`, `UR-R`, `UR-F`. Recoverable automatically, recoverable manually, unrecoverable but reversible by other means, unrecoverable and final. |
| **Inherent safety** | A surface on which unrecoverable-and-final failures are not reachable. |
| **The absent-X pattern** | `absent_gate_decision()`, `absent_margin_assessment()`, `absent_margin_profile()`, `absent_determination_profile()`, `absent_readback()`, `absent_market_profile()`. Six named functions so that "what happens when nobody established this" has one auditable answer rather than a convention repeated at every call site. |
| **Fail-safe, not fail-open** | The default under missing evidence is always the conservative branch. Most systems degrade toward permissiveness under load; this one degrades toward refusal. |
| **`NOT_ASSESSED` vs `NONE_DISCLOSED`** | "Nobody read the rulebook" versus "we read it and it grants nothing." Same conservative treatment, completely different remedies. Collapsing them lets an unread venue pass as a clean one. |
| **Conformance cycle** | The internal work of proving a new venue's rules are met. What this framework compresses. Distinct from market access, which it does not. |

---

## 3. Deliberately not used

The refusals. Each one is a claim this framework declines to make, and every one of them is enforced somewhere in code or in a test rather than left to discipline.

| Not used | Why | Say instead |
| --- | --- | --- |
| Cover-2, default waterfall, guarantee fund sizing, resource adequacy | Infrastructure-internal. Unobservable from the participant seat, and using the words would claim visibility this framework does not have. | Nothing. These are not its to discuss. |
| "PFMI-compliant", "observant of the principles" | The standards address infrastructures and their supervisors. A participant is not an addressee, and the claim is a category error visible to anyone who works with the standard. | "Consumer of mandated disclosure" |
| "Predicted margin", "estimated margin", "expected call" | Margin quantum is a deterministic function of stochastic and partly discretionary inputs. No component returns a forecast and no interface is shaped so a consumer could infer one is on offer. | "Classification of a supplied figure" |
| "The trade failed" (in a netted system) | Novation and netting destroyed the trade-to-obligation correspondence before settlement ran. Per-trade attribution is an inference presented as an observation. | "The net position failed" |
| "Resubmit", "retry", "reissue" | On a gross-final rail, re-issuing a queued instruction creates a duplicate payment that cannot be reversed. There is no such function, and a test asserts its absence. | "Classify; a human re-issues, or does not" |
| "Submitted", "executed", "sent" | This framework holds no credential and presses no button. `is_submission` is pinned to `Literal[False]`, which makes a submission object unconstructible rather than merely discouraged. | "Prepared for the entitled member to submit" |
| "Settled" for an accepted-not-posted status | It looks settled and is not. | `ACCEPTED_NOT_POSTED` |
| "Failed" for a queued payment, or for silence | A queue is not a failure, and an unacknowledged instruction is not a rejection. Both errors produce the same duplicate payment. | `WILL_QUEUE`; "nothing established" |
| "Verified" for an unpopulated profile | Every registry ships with its entries flagged. An unattributed profile is indistinguishable from a guess. | `UNVERIFIED` / `NOT_ASSESSED` |
| "Real-time" | Every gate and model here is pure, with no I/O and no clock. That is what makes a decision replayable from its recorded inputs. | "Computed per request from supplied state" |
| "The AI decides", "autonomous" | Tier 1 is deterministic. Tier 2 enumerates from a pre-declared registry and escalates on an empty match. Nothing updates its own decision function from experience. | "Bounded autonomy over an approved-path registry" |
| "GTM acceleration" | Market access, credentialing and entitlement are not compressible by software. Claiming otherwise is the fastest way to lose a technical audience. | "Conformance-cycle acceleration" |

---

*Terminology is load-bearing here. If a term in section 2 starts appearing in the wild with a looser meaning than the one above, that is a doctrine problem before it is a documentation problem.*
