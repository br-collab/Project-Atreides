# `aureon.contracts` — typed custody substrate

This package is the **machine-checkable encoding** of what custody
operations *are* under Aureon governance. Every model traces back to a
specific commitment in `doctrine/AUR-CANONICAL-001-v1_6.md` or
`doctrine/AUR-CUSTODY-001-v1_0.md`. Doctrine is the source of truth;
this package operationalises the doctrine for downstream layers.

## Module map

| Module | Doctrine reference | Purpose |
| --- | --- | --- |
| `failure_mode.py` | AUR-CUSTODY-001 v1.0 §VIII (also §VI of canonical) | Four-class taxonomy: RA / RM / UR-R / UR-F |
| `inherent_safety.py` | AUR-CUSTODY-001 v1.0 §IX + AUR-CANONICAL-001 v1.6 Axiom 10 | Twenty inherent-safety surfaces in 1:1 FIAT/digital parity |
| `settlement.py` | AUR-CUSTODY-001 v1.0 §V | Eleven settlement methods (DvP-1/2/3, DvD, PvP, FoP, atomic, conditional, triparty, bilateral, CCP-cleared) as a discriminated union |
| `asset_class.py` | AUR-CUSTODY-001 v1.0 §III | Ten major asset categories + EMERGING; FIAT / TOKENIZED / NATIVE_DIGITAL representation axis |
| `quorum.py` | AUR-CUSTODY-001 v1.0 §VII | 3-of-5 default quorum; five independence requirements; six-step ceremony state |
| `dsor_stub.py` | AUR-CANONICAL-001 v1.6 Layer 2 (Kaladan) + Axioms 1, 3, 4 | Minimum DSOR lineage fields every operation carries |
| `custody_object.py` | AUR-CUSTODY-001 v1.0 §IV | Five custody object categories (ordinary, pledged, SMA, tokenized, native digital) as a discriminated union |
| `operations/base.py` | AUR-CUSTODY-001 v1.0 §§IV / V / VII / VIII / IX | Base `CustodyOperation` with the four architectural cross-validators |
| `operations/equity.py` | AUR-CUSTODY-001 v1.0 §V Equities | Long buy/sell, short sale (Reg SHO locate), securities lending, conversion, etc. |
| `operations/fixed_income.py` | AUR-CUSTODY-001 v1.0 §V Fixed Income | Outright, when-issued, repo (term/triparty/bilateral), buy-sell-back, MBS |
| `operations/fx.py` | AUR-CUSTODY-001 v1.0 §V FX | Spot, forward, NDF (with fixing date), swap, option |
| `operations/derivatives.py` | AUR-CUSTODY-001 v1.0 §V Derivatives | Listed (futures/options) + OTC (give-up, allocation, novation, compression, termination, exercise, expiry) + margin |
| `operations/funds.py` | AUR-CUSTODY-001 v1.0 §V Funds | Subscription, redemption, exchange (with target fund), capital call, distribution, side pocket, MMF operations |
| `operations/structured.py` | AUR-CUSTODY-001 v1.0 §V Structured Products | Subscription, paydown, call, contingent acceleration (with triggering event), restructuring |
| `operations/tokenized.py` | AUR-CUSTODY-001 v1.0 §V Tokenized Securities | Mint / burn (inherent-safety: tokenized issuer ops), on-chain transfer, atomic swap, smart-contract execution, programmable distribution |
| `operations/digital.py` | AUR-CUSTODY-001 v1.0 §V Native Digital Assets | Transfer, staking/unstaking/slashing/validator rewards, DeFi, NFT ops, airdrops, governance vote, key ceremonies, cold storage |
| `operations/lifecycle.py` | AUR-CUSTODY-001 v1.0 §V Lifecycle and Exception Handling | Buy-in, sell-out, partial settlement, cancellation, rebooking |

## The four architectural cross-validators on `CustodyOperation`

The base operation enforces the four doctrinal rules every operation
must satisfy. If any of these fails, `pydantic.ValidationError` is
raised at construction time — the operation never reaches an agent.

1. **`failure_mode_class == UR_F` ⇒ `inherent_safety_surface` set**
   (per AUR-CUSTODY-001 v1.0 §VIII: UR-F operations on non-inherent-
   safety surfaces are doctrine integrity gaps).
2. **`inherent_safety_surface` set ⇒ `quorum_authority` set** (per
   AUR-CUSTODY-001 v1.0 §IX + AUR-CANONICAL-001 v1.6 Axiom 10: no
   single authority on the loss path).
3. **`inherent_safety_surface` set ⇒ `lineage.authority_tier == QUORUM`**
   (per AUR-CUSTODY-001 v1.0 §VII: a quorum-required operation cannot
   be authorised by any single CAOM tier).
4. **`quorum_authority` set ⇔ `lineage.authority_tier == QUORUM`**
   (consistency: the two cannot disagree).

## What this layer is not

This is the **typed substrate**, not the runtime. The package does not
include:

- Agent implementations (the Aureon Asset-Services Workforce — in
  `aureon/agents/` as future work).
- Quorum ceremony execution (signature collection, cryptographic
  signing infrastructure, ceremony state machine — future work).
- DSOR record assembly and persistence (`aureon/dsor/` — future work).
- Rail integration (FIAT-rail governance gate, atomic settlement
  governance, PORTS-aligned wholesale activation — `aureon/rails/`,
  future work).
- Product-specific specifications (`AUR-CUSTODY-FED-001` for Federate,
  `AUR-CUSTODY-INST-001` for Sovereign — future work).

See `FOLLOW-UPS.md` at the repo root for the full out-of-scope list.

## Adding a new operation type

1. Add an enum value to the relevant per-asset-class
   `*TransactionType` enum.
2. If the new type carries asset-class-specific fields, add them to
   the operation model with a per-type validator.
3. If the new type is on an inherent-safety surface, declare the
   surface and provide a quorum-authority record at construction; the
   base validators enforce the architectural rules.
4. Add positive and negative tests under
   `tests/contracts/operations/`.

## Adding a new asset-class operation module

1. Create `aureon/contracts/operations/<asset_class>.py` with a
   `*TransactionType` enum and an `<AssetClass>Operation` model
   subclassing `CustodyOperation` with `kind: Literal["<asset_class>"]`.
2. Add the new model to `CustodyOperationUnion` in
   `aureon/contracts/operations/__init__.py`.
3. Re-export from `aureon/contracts/__init__.py`.
4. Add the corresponding test module under
   `tests/contracts/operations/`.
