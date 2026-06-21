# AUR-CUSTODY-001

**Aureon Custody Operational Doctrine**
**v1.0 · Aureon Doctrine v1.6**

| Field | Value |
|---|---|
| Document ID | AUR-CUSTODY-001 · Aureon Custody Operational Doctrine |
| Version | v1.0 |
| Doctrine Version | Aureon Doctrine v1.6 (this document advances v1.5.1 → v1.6, the version log advancement the canonical has anticipated since v1.5) |
| Author | Guillermo "Bill" Ravelo |
| Academic | Columbia University · M.S. Technology Management — capstone research track |
| Parent Doctrine | Aureon Consolidated Canonical Doctrine v1.5.1 (AUR-CANONICAL-001) |
| Predecessor Advancement | AUR-MARKET-001 v1.0 (advanced v1.9 → v2.0) |
| Architectural Prerequisites | AUR-CANONICAL-001 v1.5 (Axiom 10 inherent-safety, three-class failure-mode taxonomy RA/RM/UR, quorum authority primitive) · AUR-CUSTODY-OBJ-001 v1.0 (custody object inventory) |
| Anticipated Successor Documents | AUR-CUSTODY-FED-001 (Atreides Federate Phase 1 operational specification) · AUR-CUSTODY-INST-001 (Atreides Sovereign operational specification) |
| Audience | Public — academic framework publication |
| Status | Pre-commercial · academic research framing · paper trading deployment |
| Classification | Public — academic framework publication (MIT-licensed code) |

---

# I. PURPOSE AND SCOPE

## Purpose

This doctrine specifies what custody is in the Aureon framework. It operationalizes the architectural prerequisites established in canonical v1.5 (Axiom 10 inherent-safety, the three-class failure-mode taxonomy, the quorum authority primitive) within the custody domain. It builds on the custody object inventory established in `AUR-CUSTODY-OBJ-001 v1.0` and provides the shared operational foundation that the two anticipated product-specific custody specifications — `AUR-CUSTODY-FED-001` (Atreides Federate, Phase 1 governance overlay) and `AUR-CUSTODY-INST-001` (Atreides Sovereign, institutional displacement) — inherit from.

This doctrine is the v1.6 advancement of the Aureon canonical doctrine that the canonical itself has anticipated since v1.5. The canonical's Section VIII open items names custody as *"the next major doctrine addition... Anticipated as the largest single doctrine addition since v1.0."* This document delivers that work substantively. The canonical is updated separately to absorb v1.6 into its version log.

The doctrine is necessary now because every downstream custody work — operational specifications for Sovereign and Federate, code implementations of custody capability, regulatory engagement on custody operations, capstone treatment of custody architecture — depends on the framework first specifying what custody operations *are* under Aureon governance. Without this specification, all downstream custody work either guesses at the framework's commitments or re-derives them ad-hoc, which is the doctrine-implementation gap the framework is built to prevent (Axiom 1 — doctrine before execution).

## Why This Doctrine Is the Foundation, Not the Product Specification

Custody under Aureon governance has two product expressions per the segmentation doctrine (`AUR-SEGMENT-001 v1.0`): Atreides Sovereign for tier-1 institutional buyers replacing legacy custody platforms, and Atreides Federate for middle-market buyers consuming custody as a service through governance overlay above existing custodians. The two products operate at different scales, serve different buyers, and have different commercial trajectories. They share the architectural foundation: the same custody object inventory, the same agent workforce, the same DSOR audit surface, the same authority routing, the same inherent-safety standard.

This doctrine specifies the shared foundation. The product-specific operational specifications — what the Sovereign deployment looks like when running at a tier-1 custodian, what the Federate deployment looks like when running as overlay above multiple custodians — are the work of `AUR-CUSTODY-INST-001` and `AUR-CUSTODY-FED-001` respectively. Those documents inherit from this one without restating its commitments.

The structural advantage: defining custody once at the framework level prevents the doctrine drift that occurs when product-specific specifications repeat foundational commitments and gradually diverge. The Sovereign and Federate custody specifications are operational addenda; the architectural commitments are codified here.

## Scope

This doctrine specifies nine things: the operational definition of custody under Aureon governance; the asset-class universe that custody under Aureon governance handles (the durable architectural axis); the mapping of the custody object inventory onto operational custody workflows; the comprehensive enumeration of transaction types and settlement methods that custody under Aureon governance commits to handle (the variable operational layer beneath the asset-class architecture); the custody-specific roles added to the Aureon Asset-Services Workforce (renamed from the historical eFICC framing to match the asset-class breadth); the custody-specific failure-mode taxonomy refinement (the four-class extension anticipated in canonical v1.5); the operational quorum authority specification (the primitive defined in canonical v1.5 Section VI, operationalized here for custody); the inherent-safety architecture applied to custody surfaces per Axiom 10; and the forward-state framework covering atomic settlement, 24/7 operational continuity, and selective FIAT/tokenized custody for the 5-10 year horizon.

It does not specify operational details of either Sovereign or Federate deployments — those are the domain of `AUR-CUSTODY-INST-001` and `AUR-CUSTODY-FED-001` respectively. It does not specify pricing or commercial terms — those are commercial documents maintained separately. It does not specify the implementation code for custody capability — that is the domain of subsequent engineering work that operationalizes this doctrine in the Project-Atreides codebase. It does not specify the cash-account API integration for Federate Phase 1 — that is FED-001's domain because it is product-specific.

---

# II. WHAT CUSTODY IS UNDER AUREON GOVERNANCE

## Operational Definition

Custody under Aureon governance is the set of operational activities by which an institutional party holds, services, transfers, encumbers, releases, valuates, and audits financial assets on behalf of beneficial owners, under doctrine-grade governance that produces a complete, replayable audit lineage for every operation, across the full variety of transaction types and settlement methods that institutional custody accommodates.

Five components in that definition matter precisely:

**"On behalf of beneficial owners"** — Custody operations are always agency operations. The custodian holds title or control on behalf of a beneficial owner whose ownership interest is the custodian's primary duty. This is the legal and regulatory grounding of custody and it is the boundary that distinguishes custody from proprietary holding. Aureon's custody framework operates under this agency posture; Aureon does not custody for itself.

**"Doctrine-grade governance"** — Custody operations under Aureon are not just performed correctly; they are performed under explicit doctrine constraints with full audit lineage. Every custody operation produces a DSOR record stamped with the active doctrine version, the authority routing per CAOM-001, the agent telemetry under Tier 1 deterministic execution, and the lineage fragments that allow regulator-grade replay.

**"Complete, replayable audit lineage for every operation"** — The doctrine standard is not "most operations are auditable" or "operations above material magnitude produce full records." The standard is every operation, at every magnitude, produces complete lineage. This is what distinguishes custody under Aureon from custody under incumbent platforms whose audit trails are assembled retroactively from fragmented system logs.

**"Across the full variety of transaction types"** — Modern institutional custody encompasses dozens of distinct transaction types per asset class, each with its own settlement mechanics, counterparty profiles, failure modes, and governance implications. Custody under Aureon governance must accommodate the full variety, not just the procedural majority. The hard cases — short sales with locate failure, repo with mid-term counterparty downgrade, pledged assets with subordinated lien disputes, failed trades requiring buy-in or sell-out, conditional settlements contingent on regulatory approval — are where institutional custody actually earns its fees and where the failure modes Aureon's framework is built to govern actually live. Section IV below enumerates the transaction-type universe that custody under Aureon governance commits to handle.

**"And settlement methods that institutional custody accommodates"** — Settlement of a custody operation can occur through any of multiple methods: gross-gross DvP, gross-net DvP, multilateral net DvP, delivery-versus-delivery for security-for-security exchanges, payment-versus-payment for FX, free-of-payment transfers, atomic settlement on tokenized rails, conditional settlements, triparty arrangements, bilateral arrangements. Each method has its own settlement-risk profile, counterparty exposure, and operational mechanics. The doctrine commits custody operations under Aureon governance to handle the full settlement-method variety, with the appropriate governance overlay for each method. Section IV below enumerates the settlement-method taxonomy.

## What the Top 5 Global Custodians Currently Do

To anchor the doctrine in operational reality, the framework references current institutional custody practice at the five largest global custodians: BNY Mellon, State Street, JPMorgan Chase, Citi (specifically Citi Services), and BNP Paribas Securities Services. Together these institutions custody approximately $200 trillion in assets under custody and administration, supporting the institutional asset management, broker-dealer, sovereign wealth, central bank, and corporate treasury client bases globally.

Their operational custody practice consists of, broadly:

**Asset safekeeping at depositories and sub-custodians.** The custodian maintains accounts at central securities depositories (DTCC for US securities, Euroclear and Clearstream for European, JASDEC for Japan, and analogous depositories in other jurisdictions) and at sub-custodian banks in jurisdictions where direct depository membership is impractical. Beneficial owner interests are tracked on the custodian's books against depository or sub-custodian holdings.

**Transaction settlement.** When the beneficial owner trades, the custodian receives settlement instructions, validates them against custody records, and effects settlement through the appropriate depository or sub-custodian. Settlement is typically T+1 for US equities and Treasuries, T+2 for some international securities, real-time for some payment instruments. The custodian's role is to ensure delivery-versus-payment (DVP) integrity and to update custody records to reflect the post-settlement position.

**Corporate actions processing.** When the issuer of a custodied security takes a corporate action (dividend payment, stock split, merger, rights offering, tender offer), the custodian receives notification from the depository or issuer, applies the action to beneficial owner accounts according to elected or default treatment, processes any required cash flows, and updates custody records. Corporate actions are operationally complex because they vary by issuer, jurisdiction, action type, and beneficial owner instruction.

**Income collection and tax processing.** Coupon payments, dividends, distributions, and other income payments are received by the custodian, allocated to beneficial owner accounts, processed for withholding tax according to the beneficial owner's tax status and jurisdiction, and reported per regulatory requirements (1099 in US, equivalent in other jurisdictions).

**Proxy voting and shareholder services.** The custodian receives proxy materials from issuers, distributes them to beneficial owners according to instructions or defaults, collects and aggregates votes, and submits them to issuer agents on the appropriate timeline.

**Collateral management.** When custodied assets are pledged as collateral (repo, securities lending, derivatives margin, lending facility), the custodian tracks the encumbrance, processes margin calls and collateral substitutions, releases assets when the encumbrance is satisfied, and maintains lineage of every encumbrance event.

**Reporting and audit support.** The custodian produces position reports, transaction confirmations, income statements, tax documents, and audit packages on the schedule and format the beneficial owner and applicable regulators require. The reporting is reconciled against the custodian's books and the beneficial owner's books before delivery.

**Cash management.** The custodian holds cash balances in depository accounts on behalf of the beneficial owner, sweeps cash to short-term investment vehicles per the beneficial owner's investment policy, processes cash flows from securities operations and beneficial owner instructions, and provides cash position reporting integrated with securities positions.

These eight functional areas — safekeeping, settlement, corporate actions, income, proxy, collateral, reporting, cash management — define the modern institutional custody surface. The Top 5 custodians perform all eight at scale across multiple asset classes, multiple jurisdictions, and multi-trillion-dollar AUC bases. Their operational architectures differ in implementation but converge on this functional surface.

## How the Top 5 Differentiate by Client Type

The Top 5 do not compete on undifferentiated custody. Each has built operational depth in specific client segments, and institutional buyers select custodians based on segment fit as much as on platform capability. The doctrine names this reality because custody under Aureon governance must be capable of serving every segment the Top 5 individually serve, while the Top 5 individually do not.

**JPMorgan — systematic strategy funds and prime brokerage integration.** JPMorgan is the dominant custodian for systematic strategy funds: CTAs (commodity trading advisors), quant equity funds, systematic macro, statistical arbitrage funds, and high-frequency-adjacent strategies. The reason is operational depth: systematic funds have transaction volumes orders of magnitude higher than discretionary funds, require deep prime brokerage integration for short-side and leveraged exposures, depend on multi-asset margin offset across futures and securities and derivatives, and demand technology integration that smaller custodians cannot match. JPMorgan's custody platform is purpose-built for this client profile, and most institutional systematic strategies custody there as a result. The doctrine acknowledges this: any custody framework that aspires to serve the systematic fund segment must operationally match the JPMorgan service model in volume capacity, prime brokerage integration, multi-asset margin, and technology depth.

**State Street — institutional asset managers and ETFs.** State Street is the dominant custodian for traditional institutional asset management, particularly the largest mutual fund and ETF complexes (BlackRock, Vanguard, State Street's own SPDR family, Franklin Templeton, T. Rowe Price). The operational depth is in fund accounting, NAV calculation at scale, ETF creation/redemption mechanics, and transfer agency. State Street's IFS (Investor Services) business is built around the asset management client lifecycle.

**BNY Mellon — global custody breadth and tri-party collateral.** BNY Mellon is the largest custodian by AUC and the dominant tri-party agent in US repo and securities lending. Its strength is breadth of asset class coverage, depth of global sub-custody network, and the operational scale of its tri-party collateral management business. BNY Mellon also has the largest corporate trust business globally, handling escrow, IPA, and structured product administration at institutional scale.

**Citi — cross-border emerging markets and FX-bundled custody.** Citi Services has the deepest emerging market sub-custody network among the Top 5, supporting institutional clients across jurisdictions where direct depository access is impractical. Citi's strength is in cross-border operations: FX-bundled settlement, multi-currency custody, emerging market securities lending, and the operational complexity of supporting institutional clients investing across 60+ markets globally.

**BNP Paribas Securities Services — European institutional and post-trade integration.** BNP Paribas is the European institutional anchor among the Top 5, with operational depth across European market infrastructure (Euroclear, Clearstream, T2S, CSDR compliance), institutional asset management custody, and the post-trade integration that European institutional clients require. BNP's strength is in serving European institutional clients across the European market structure.

The differentiation matters for the Aureon framework because custody under Aureon governance must be capable of serving every segment — systematic funds with JPM-class volume and integration, asset managers with State Street-class fund accounting depth, global custody with BNY-class breadth and tri-party capability, emerging markets with Citi-class cross-border depth, European institutional with BNP-class market structure integration. The product specifications (`AUR-CUSTODY-INST-001` for Sovereign, `AUR-CUSTODY-FED-001` for Federate) detail the operational implementation of each segment fit; the foundation doctrine commits the framework to capability across all segments.

## Why the Aureon Framework Specifies Custody Differently

Aureon does not propose to do custody differently in operational substance. The eight functional areas above are real custody work and any institutional custody framework must address them. What Aureon proposes is to do custody differently in operational *governance*: under unified doctrine with complete audit lineage, with agent-operated workforce displacing procedural execution, with multi-rail governance covering both traditional and tokenized settlement, and with inherent-safety architecture per Axiom 10 protecting the unrecoverable failure modes that single-point-failure custody operations expose.

The substantive operational work is the same. The governance architecture above the work is what the framework changes. This distinction matters because it positions Aureon as architectural alternative rather than as displacement of incumbent custodian capability — consistent with the framing principle established in `AUR-MARKET-001 v1.0`. The Top 5 custodians do real, valuable, sophisticated custody work. Aureon offers a governance architecture that institutions of various scales can deploy to operate at next-generation architectural maturity, whether they are tier-1 incumbents (Sovereign), middle-market firms (Federate), or institutions of varying configurations between those poles.

---

# III. ASSET-CLASS UNIVERSE UNDER AUREON CUSTODY GOVERNANCE

This section establishes the durable architectural axis of custody under Aureon governance. Custody is asset-class-bounded only by the legal definition of custodiable assets — not by current operational practice, not by the asset categories any individual custodian happens to support today, and not by the post-trade-shaped mental model that organizes most custody platforms historically. The doctrine commits the framework to every asset class that institutional beneficial owners legally hold, including categories that emerge over the doctrine's operational life as new asset structures are created.

This is the architectural choice that makes the doctrine durable. Settlement methods change — T+2 became T+1, T+1 will become T+0, T+0 will become atomic, atomic will become PORTS-aligned wholesale tokenized. Each transition is operationally significant but architecturally local. What does not change is *what custody is at the asset level*: the agency relationship, the title clarity, the lineage requirement, the encumbrance tracking, the corporate action handling per asset's mechanics, the beneficial owner accounting. Assets are the durable nouns of custody. Settlement methods are the verbs that vary across rails, regulations, and infrastructure evolution.

## The Architectural Commitment

Custody under Aureon governance handles every asset class possible. The framework is not bounded to traditional securities, not bounded to financial instruments, not bounded to the asset categories that fit any specific settlement infrastructure. The bounding is at the legal level: if an asset can be legally held by a custodian on behalf of a beneficial owner under any qualified custody framework — banking, trust, broker-dealer, qualified custodian, special purpose depository institution, or future regulatory category — custody under Aureon governance commits to handle it.

This is a maximalist commitment by design. The Lone Survivor framing applies: the framework wins by being the only architecture that supports every asset class an institutional buyer might want to consolidate under unified governance, rather than by matching the asset coverage of any single incumbent custodian. Top 5 incumbents each cover impressive subsets of the universe; none covers all of it. The Aureon framework's competitive position is built on the architectural commitment to the full universe, with operational specifications that detail per-asset-class implementation as the framework deploys.

## Asset-Class Categories Custody Under Aureon Governance Handles

The enumeration below is comprehensive but not exhaustive. The architectural commitment is to the full universe, not to the specific list. Operational specifications detail per-category implementation depth at deployment.

### Traditional Financial Securities

**Equities.** Common stock, preferred stock, depository receipts (ADRs, GDRs), restricted stock, employee stock options held in custody, dual-class share structures, voting and non-voting variants. Domestic and international across all major and emerging market exchanges.

**Fixed Income — Sovereign and Quasi-Sovereign.** US Treasuries (bills, notes, bonds, TIPS, FRNs, STRIPS), agency securities (Fannie Mae, Freddie Mac, Ginnie Mae, FHLB, Farm Credit), municipal securities (general obligation, revenue, taxable munis, BABs), supranational debt (World Bank, IMF, regional development banks), sovereign debt across developed and emerging markets, sovereign-guaranteed instruments.

**Fixed Income — Corporate and Structured.** Investment grade corporate bonds, high yield corporate bonds, convertible bonds, perpetual bonds, contingent convertibles (CoCos), preferred securities, hybrid capital instruments (AT1, T2), commercial paper, certificates of deposit, bankers acceptances, mortgage-backed securities (agency and non-agency), asset-backed securities (auto, credit card, student loan, equipment), commercial mortgage-backed securities, collateralized loan obligations, collateralized debt obligations, residential mortgage-backed securities including non-QM and re-performing loans.

**FX and Currency.** Major currencies (USD, EUR, JPY, GBP, CHF, CAD, AUD, NZD), commodity currencies (NOK, SEK, ZAR, MXN, BRL), emerging market currencies (CNY/CNH, INR, KRW, TWD, IDR, THB, PHP, MYR, VND, PLN, CZK, HUF, RON, TRY, ILS, EGP, NGN, KES), restricted currencies traded via NDF, frontier market currencies via correspondent banking arrangements.

**Listed Derivatives.** Equity index futures and options, single stock futures and options, interest rate futures (Treasury futures, SOFR futures, Eurodollar legacy), commodity futures (energy, metals, agriculturals, softs), FX futures and options, VIX and volatility derivatives, weather derivatives, freight derivatives, electricity futures.

**OTC Derivatives.** Interest rate swaps (vanilla, basis, OIS, cross-currency), credit default swaps (single-name, index, tranche), equity swaps and total return swaps, FX forwards and swaps, commodity swaps, variance swaps and volatility derivatives, exotic options (barrier, lookback, digital, basket, rainbow), structured derivatives, bespoke OTC products.

### Funds and Pooled Investment Vehicles

**Mutual funds.** Open-end equity, fixed income, balanced, target date, money market (constant NAV and floating NAV), 40 Act funds, UCITS funds, alternative mutual funds.

**Exchange-traded funds.** Equity ETFs, fixed income ETFs, commodity ETFs, currency ETFs, leveraged and inverse ETFs, actively managed ETFs, smart-beta and factor ETFs, thematic ETFs, ETFs of digital assets (spot Bitcoin, spot Ethereum, futures-based crypto ETFs).

**Hedge funds.** Long/short equity, market neutral, event driven, distressed, macro (discretionary and systematic), managed futures and CTA, multi-strategy, fund of funds, statistical arbitrage, quantitative equity, fixed income arbitrage, convertible arbitrage. Custody for systematic strategy funds — the JPM-dominated segment specifically named in Section II — has distinct operational requirements that the framework supports natively.

**Private equity.** Buyout funds, growth equity, venture capital, secondary funds, fund of funds, co-investment vehicles, continuation vehicles, GP stake funds, search funds, private equity SMAs.

**Private credit and direct lending.** Direct lending funds, mezzanine funds, distressed credit, special situations, opportunistic credit, BDCs (Business Development Companies), interval funds focused on private credit, private credit SMAs.

**Real estate funds.** Open-end and closed-end real estate funds, REITs (public and non-traded), real estate operating companies, real estate debt funds, opportunistic and value-add real estate, infrastructure funds, timber and farmland funds.

**Other alternatives.** Litigation finance funds, music royalty funds, life settlement funds, art funds, wine funds, cryptocurrency hedge funds and venture funds, DeFi-focused funds, tokenized fund structures.

### Physical and Financial Commodities

**Precious metals.** Gold (LBMA-approved bars, allocated and unallocated, vault custody at LBMA-approved facilities including London, Zurich, Singapore, New York), silver, platinum group metals (platinum, palladium, rhodium), specialty metals.

**Base metals.** Copper, aluminum, zinc, lead, nickel, tin, warehoused at LME-approved locations globally.

**Energy commodities.** Crude oil and refined products in storage, natural gas in pipeline and storage facilities, refined product inventories, LNG cargoes, coal stockpiles.

**Agricultural commodities.** Grain (corn, wheat, soybeans, rice, oats), softs (sugar, coffee, cocoa, cotton, orange juice), livestock and meat, dairy, lumber.

**Carbon and environmental.** Voluntary carbon market credits (VCS, Gold Standard, ACR, CAR), compliance market allowances (EU ETS, RGGI, California Cap-and-Trade, China ETS, UK ETS), renewable energy certificates (RECs), white certificates, water rights, biodiversity credits.

### Real Estate and Real Assets

**Direct real estate interests.** Title to real property held in trust or custody structures, Delaware Statutory Trusts (DSTs), Tenant-In-Common (TIC) interests, ground leases, air rights, mineral rights, royalty interests, real estate partnership interests, opportunity zone investments.

**Infrastructure assets.** Transportation infrastructure interests (toll roads, ports, airports, rail), energy infrastructure (pipelines, transmission, generation, renewables), digital infrastructure (data centers, fiber, towers), social infrastructure (schools, hospitals via PPP/PFI structures), water and waste infrastructure.

**Natural resources.** Timber, farmland, water rights, mineral and royalty interests, oil and gas working interests, oil and gas overriding royalty interests, mining concessions, fishing rights.

### Insurance and Reinsurance

**Insurance-linked securities.** Catastrophe bonds, mortality bonds, longevity bonds, sidecars, industry loss warranties.

**Insurance contracts in custody.** Life settlements, annuity contracts in custody, structured settlement obligations, longevity swaps, mortality swaps.

**Reinsurance interests.** Reinsurance treaty participations, retrocession arrangements, capital relief structures, alternative reinsurance vehicles (Bermuda, Cayman, Lloyd's syndicate participations).

### Intellectual Property and Royalty Streams

**Music royalties.** Mechanical royalties, performance royalties, synchronization rights, master recording rights, publishing rights catalogs.

**Patent portfolios.** Defensive patent pools, monetization patent portfolios, standard-essential patent portfolios, pharmaceutical patent royalty streams.

**Other IP.** Trademark portfolios held in trust, copyright portfolios, software licensing royalties, franchise royalty streams, brand licensing streams.

### Trade Finance and Receivables

**Trade receivables.** Invoice discounting positions, factoring portfolios, supply chain finance interests, export credit insurance-backed receivables.

**Trade finance instruments.** Letters of credit positions, documentary credits, standby letters of credit, bank guarantees, performance bonds.

**Loans.** Syndicated loans (par and distressed), bilateral loans, middle market loans, leveraged loans, second lien and mezzanine, unitranche, NAV facilities, subscription credit facilities.

### Tokenized Representations of All Above

Every asset class above can be tokenized — represented as a digital token on a blockchain or distributed ledger — and custody under Aureon governance handles the tokenized representation natively under the same framework as the underlying asset.

**Tokenized traditional securities.** Tokenized Treasuries (Ondo OUSG, BlackRock BUIDL, Franklin Templeton FOBXX, WisdomTree WTGXX, and successors), tokenized corporate bonds, tokenized equity (registered under Reg D, Reg S, Reg A+, or future tokenized issuance frameworks), tokenized mutual funds and ETFs.

**Tokenized funds.** Tokenized hedge fund interests, tokenized private equity interests, tokenized real estate funds, tokenized credit funds.

**Tokenized commodities.** Tokenized gold (PAXG, XAUT, and successors), tokenized silver, tokenized oil, tokenized agricultural commodities, tokenized carbon credits.

**Tokenized real assets.** Fractionalized real estate tokens, fractionalized art tokens, fractionalized collectibles tokens, fractionalized music royalty tokens.

**Tokenized cash.** Stablecoins (USDC, USDT, PYUSD, FDUSD, and successors), tokenized money market funds, tokenized bank deposits (JPM Coin, Citi Token Services), wholesale tokenized currency when operationally available (PORTS-aligned, Project Agorá outcomes, Project Cedar evolution, central bank digital currency wholesale variants).

### Native Digital Assets

**Cryptocurrencies.** Bitcoin, Ethereum, and the broader universe of native protocol tokens. Custody-grade handling of layer-1 native tokens across all major and emerging chains, layer-2 tokens, and protocol-specific governance tokens.

**Staking positions.** Native staked positions across proof-of-stake protocols (Ethereum, Solana, Cardano, Polkadot, Cosmos, Avalanche, Sui, Aptos, and successors), liquid staking positions (Lido, Rocket Pool, and successors), restaking positions (EigenLayer and successors).

**DeFi protocol positions.** Lending positions (Aave, Compound, and successors), liquidity provision positions (Uniswap, Curve, and successors), yield farming positions, governance token positions, real-world asset (RWA) protocol positions.

**Non-fungible tokens (NFTs).** Art NFTs, collectibles, gaming assets, intellectual property NFTs, real-world asset-backed NFTs, soul-bound tokens for identity and credentialing.

### Alternative and Specialty Assets

**Art and collectibles.** Fine art held in trust custody arrangements, museum-quality collectibles, watches, jewelry, rare books and manuscripts, sports memorabilia, trading cards.

**Wine and spirits.** Investment-grade wine cellared at qualified storage facilities, rare whiskey casks held in bond, premium spirits in storage.

**Litigation finance.** Litigation portfolio interests, single-case litigation finance positions, claims portfolios, judgment monetization interests.

**Sports and entertainment.** Athlete contract income streams, entertainment royalty streams, sports franchise minority interests, media rights interests.

### Emerging and Future Asset Categories

The architectural commitment extends to asset categories that emerge during the doctrine's operational life. Examples currently in development that the framework anticipates:

- Tokenized real-world assets (RWA) across categories not yet operationally significant
- Programmable money instruments combining smart contract logic with traditional currency representation
- Decentralized identity and reputation assets
- Genomic and biological data assets under emerging custody frameworks
- AI-generated intellectual property assets
- Space and orbital assets (satellite capacity, lunar resource interests, space-based asset rights)
- Climate and biodiversity asset categories beyond current voluntary carbon market structures
- Perpetual royalty and revenue-share instruments enabled by smart contract automation
- Synthetic asset representations across previously incompatible asset classes

The doctrine does not enumerate emerging categories prescriptively. The architectural commitment is that custody under Aureon governance treats new asset categories as configurable extensions to the existing framework — new doctrine versions absorb new categories through the propose/approve workflow per canonical Section VIII, without requiring framework-level rebuild.

## Architectural Implications of Asset-Class Breadth

The commitment to every asset class possible has architectural consequences the doctrine acknowledges explicitly.

**Settlement methods are subordinate, not foundational.** Settlement is how a custody operation completes — important operationally, variable across asset classes and over time. The doctrine treats settlement methods as a configurable layer beneath the asset-class architecture (Section V below enumerates the current methods). When a new settlement method emerges (atomic on a new chain, PORTS-aligned wholesale tokenized, an entirely novel rail not yet conceived), the doctrine absorbs it through configuration without architectural rebuild. The asset under custody does not change; only the rail by which it settles changes.

**Custodial structure is asset-class-aware.** Different asset classes require different qualified custodian arrangements. Traditional securities under broker-dealer or bank custody. Real estate under trust company custody. Digital assets under SPDI or qualified digital asset custodian. Insurance contracts under insurance regulator-supervised custody. Custody under Aureon governance recognizes the structural diversity and provides governance overlay appropriate to each — it does not require assets to fit a single custodial structure.

**Per-asset-class operational mechanics vary.** Corporate actions on equities differ from coupon payments on bonds differ from staking rewards on digital assets differ from royalty distributions on music IP. The doctrine's eight functional areas (safekeeping, settlement, corporate actions, income, proxy, collateral, reporting, cash management) apply universally but the per-asset-class operational mechanics differ. Operational specifications detail per-asset-class implementation; the foundation doctrine commits the framework to handling each.

**Regulatory framework applicability varies by asset class.** Different asset classes carry different regulatory frameworks: SEC for securities, CFTC for commodities and derivatives, OCC and bank regulators for trust custody, state insurance regulators for insurance contracts, IRS for tax-treated assets, jurisdiction-specific regulators for real estate, emerging regulatory frameworks for digital assets. Custody under Aureon governance respects the regulatory framework applicable to each asset class while operating under unified governance above the regulatory differentiation.

**Concentration limits and risk frameworks vary.** Risk concentration in traditional securities differs from concentration in real estate differs from concentration in cryptocurrency differs from concentration in commodities. The Aureon risk reporting agents (Tier 2 J-class compliance and risk monitoring per canonical Section IV) apply asset-class-aware concentration limits and risk frameworks — operational specifications detail the limit methodology per asset class.

**Beneficial owner accounting is asset-class-agnostic.** Despite the per-asset-class operational variation, beneficial owner accounting is unified. A single beneficial owner's complete custody position — across traditional securities, real estate, commodities, digital assets, alternatives — is reported under one DSOR thread. This is the unification advantage that no single Top 5 custodian provides comprehensively (because none custodies every asset class) and that custody under Aureon governance commits to architecturally.

---

# IV. CUSTODY OBJECT INVENTORY APPLIED TO OPERATIONS

`AUR-CUSTODY-OBJ-001 v1.0` specified five custody object categories: ordinary safekeeping, pledged assets, separately managed accounts (SMAs), tokenized securities, and native digital assets. This section maps those categories onto the operational custody workflows above, identifying which workflows apply to which object categories and where the governance overlays differ.

## Ordinary Safekeeping

Ordinary safekeeping is the baseline custody object: an asset held on behalf of a beneficial owner with no specific encumbrance, restriction, or specialized governance overlay beyond standard custodian operations. This is the largest custody category by volume and value across the institutional custody industry.

Operational workflows that apply: all eight (safekeeping, settlement, corporate actions, income, proxy, collateral when temporarily pledged, reporting, cash management).

Governance overlay: standard CAOM-001 authority routing for material operations; standard Tier 1 agent execution for procedural operations; standard DSOR lineage for all operations. No quorum authority required for operations of non-material magnitude.

Special considerations: the volume scale makes process automation through the Tier 1 agent workforce (Settlement Operations Analyst, Trade Support Analyst, Reconciliation Analyst, Regulatory Reporting Analyst) the primary operational efficiency path. The Tier 1 agents handle ordinary safekeeping operations deterministically with R-class guardrails per canonical Section IV.

## Pledged Assets

Pledged assets are custody objects with active encumbrance: collateral pledged to a counterparty for repo, securities lending, derivative margin, credit facility, or other secured arrangement. The encumbrance creates a third-party interest in the asset that must be tracked, respected, and discharged appropriately when the underlying obligation is satisfied.

Operational workflows that apply: settlement with encumbrance modifications, corporate actions with collateral-holder notification, income with collateral-economics handling (coupon pass-through, dividend handling per pledge terms), reporting with encumbrance disclosure, collateral management as the primary workflow.

Governance overlay: pledged-asset operations of material magnitude (large pledges, lien releases, encumbrance changes, collateral substitutions on actively-margined positions) **are quorum authority operations under Axiom 10 and the canonical v1.5 quorum primitive**. Single-authority approval is structurally insufficient because pledged-asset operations have unrecoverable failure modes — releasing pledged collateral to the wrong party, failing to update encumbrance records, missing margin calls — that cannot be undone after the fact.

The quorum authority specification for pledged assets is the primary operational instance the canonical v1.5 quorum primitive was reserved for. Section VII below operationalizes the quorum requirement for pledged-asset operations.

## Separately Managed Accounts (SMAs)

SMAs are custody objects held in named beneficial owner accounts (rather than in omnibus structures pooling multiple beneficial owners' assets together). The defining characteristic is title clarity: every asset in an SMA is identifiable to a specific beneficial owner at all times.

Operational workflows that apply: all eight, with the addition of SMA-specific reporting (per-account position reports, per-account performance attribution, per-account tax treatment, per-account corporate action elections).

Governance overlay: standard CAOM-001 authority routing; Tier 1 agent execution with SMA-specific reconciliation (Reconciliation Analyst confirms SMA-level positions match beneficial owner expectations on every reconciliation cycle); DSOR lineage stamped with SMA identifier for per-account audit reconstruction.

Special considerations: the regulatory and legal posture of SMAs is materially different from omnibus custody. SMAs are the architecture beneficial owners require when title clarity matters for tax treatment, regulatory reporting, fiduciary obligation, or beneficial owner control. Aureon's per-account DSOR lineage natively supports SMA reporting in a way that omnibus-structured incumbent custody platforms typically require additional reporting overlays to produce.

## Tokenized Securities

Tokenized securities are custody objects represented as digital tokens on a blockchain or distributed ledger, where the token represents a beneficial interest in an underlying security (Treasury, equity, fund interest, structured product, etc.). The token-to-security mapping is established by the token issuer (typically the security issuer or an authorized custodian) and is enforced by the smart-contract logic governing the token.

Operational workflows that apply: all eight, with material modifications: settlement occurs on the tokenized rail (atomic settlement potentially) rather than through traditional depository instructions; corporate actions may be implemented as smart-contract execution rather than depository messaging; income may flow through smart-contract distribution rather than custodian disbursement; reporting must reconcile on-chain state with off-chain books and records.

Governance overlay: same CAOM-001 authority routing; Tier 1 agent execution with tokenized-specific rail handling (Cato governance gate per `AUR-PT-EFICC-001` and the canonical Verana Cato specification); DSOR lineage spanning both on-chain transactions and off-chain custody records under one unified record per Axiom 4.

Special considerations: the doctrine-over-code principle from canonical Axiom 5 binds tokenized securities operations. When smart-contract logic conflicts with Aureon doctrine — for example, a smart-contract action that the doctrine would not approve, or a smart-contract default that contradicts the beneficial owner's instruction — Thifur-J holds execution and escalates per the J-class guardrails. The smart contract does not override doctrine. This is the architectural constraint that makes tokenized securities custody governable within the same framework as traditional securities custody.

## Native Digital Assets

Native digital assets are custody objects whose existence is wholly on-chain — cryptocurrencies, native protocol tokens, NFTs (non-fungible tokens), DeFi protocol positions, and other assets that have no traditional-security underlying. Custody of native digital assets is fundamentally different from custody of tokenized securities because there is no off-chain underlying to reconcile against.

Operational workflows that apply: safekeeping (private key management is the primary safekeeping work); settlement (on-chain transaction execution); income (staking rewards, protocol distributions, airdrops); collateral (DeFi protocol collateralization, on-chain repo); reporting (with on-chain transaction lineage); cash management (with stablecoin and native cryptocurrency considerations).

Governance overlay: **all material native digital asset operations are quorum authority operations under Axiom 10 and the canonical v1.5 quorum primitive**. The unrecoverable failure modes are categorically more severe than in traditional custody: an on-chain transaction sent to the wrong address has finality and cannot be recalled; a private key compromise enables unauthorized transactions that cannot be reversed; a smart-contract interaction with a malicious or buggy protocol can drain assets irrecoverably.

The quorum authority specification for native digital assets is the second major operational instance the canonical v1.5 quorum primitive was reserved for. Section VII below operationalizes the quorum requirement for native digital asset operations.

Special considerations: native digital asset custody requires private key governance architecture that traditional custody does not. Hardware security modules (HSMs), multi-party computation (MPC) cryptography, hardware wallets in cold storage, ceremony protocols for key generation and rotation, and physical security for key material custody are all part of the operational surface. The doctrine specifies the governance requirements (quorum authority, inherent-safety per Axiom 10, doctrine-over-code per Axiom 5); the operational specifications for Sovereign and Federate will detail the physical and cryptographic implementations appropriate to each product's deployment context.

---

# V. TRANSACTION TYPES AND SETTLEMENT METHODS ACROSS THE ASSET-CLASS UNIVERSE

This section enumerates the transaction types and settlement methods that custody under Aureon governance commits to handle across the asset-class universe established in Section III. The framing matters: settlement methods are the *variable operational layer* beneath the durable asset-class architecture. They change as new rails emerge (atomic, PORTS-aligned, future infrastructures not yet conceived), as regulatory regimes evolve (T+1 to T+0 to atomic), and as new asset categories require new settlement mechanics. The doctrine accommodates the variability rather than depending on the specific methods listed.

The enumeration is comprehensive for current operational reality but explicitly non-binding on future settlement evolution. Operational specifications for Sovereign and Federate (`AUR-CUSTODY-INST-001`, `AUR-CUSTODY-FED-001`) detail product-specific implementation and absorb new methods through configuration as they emerge. The architectural commitment is to handle the variety, not to lock the variety to today's mechanics.

The enumeration is structured along three dimensions: transaction types by asset class, settlement methods by operational mechanism, and lifecycle and exception handling. The pledged-asset transaction variety is treated as a fourth dimension because of its operational depth and because pledged assets carry quorum authority requirements per Section VII.

## Transaction Types by Asset Class

### Equities

**Long buy and long sell.** Outright purchase or sale of equity securities. Standard DvP settlement on T+1 (US, post-2024 transition) or T+2 (some international markets). Custody operations: trade capture, position update, cash settlement, reporting.

**Short sale (regulated under Reg SHO in US).** Sale of borrowed equity. Custody operations: locate confirmation before sale, borrow execution and pledge, sale settlement, ongoing borrow rate accrual, recall risk monitoring, ultimately covered by purchase or delivery. Failure modes include locate failure (no available borrow), recall (lender demands return), buy-in (failure to deliver triggers forced cover at unfavorable price). Each failure mode has distinct governance implications and is enumerated for treatment in operational specifications.

**Short cover.** Purchase to close an existing short position. Custody operations: trade capture, position update, borrow return, cash settlement, reporting.

**Securities lending — lender side.** Loaning custodied securities to a borrower in exchange for collateral and a borrow fee. Custody operations: loan initiation, collateral acceptance and management (cash or securities collateral), mark-to-market processing, recall execution when needed, return processing, fee accrual and collection. Failure modes include borrower default (collateral seizure required), collateral insufficiency (mark-to-market failure), failed return (recall failure triggers buy-in).

**Securities lending — borrower side.** Borrowing securities from a lender for short selling, settlement coverage, or other purposes. Custody operations: locate, borrow execution, collateral posting, ongoing fee payment, return on demand or contract termination.

**Rights subscription and warrant exercise.** Beneficial owner exercises subscription rights or warrants on custodied securities. Custody operations: subscription instruction processing, cash payment to issuer, new security receipt and position update, fractional handling.

**Conversion.** Convertible security converted to underlying common (or vice versa per terms). Custody operations: conversion instruction processing, security exchange, fractional handling, position update, reporting.

**Exchange offers and tender offers.** Beneficial owner tenders securities in response to issuer or third-party offer. Custody operations: tender election processing, security delivery, consideration receipt (cash, securities, or both), fractional handling, withdrawal processing if tender is revoked.

**In-kind transfer.** Securities moved between accounts without sale. Custody operations: transfer instruction validation, ownership chain confirmation, position update at both source and destination, no cash component.

**Restricted-stock release.** Lock-up period expiration or other restriction lifting on previously-restricted securities. Custody operations: restriction code removal, position eligibility update, regulatory notification if required.

### Fixed Income

**Outright purchase and sale.** Standard DvP settlement on T+1 (Treasuries) or T+2 (most corporates and munis). Custody operations: trade capture, position update, accrued interest calculation, cash settlement, reporting.

**When-issued (WI) trading.** Trading securities before official issuance. Custody operations: WI trade capture, conditional settlement contingent on actual issuance, settlement on issue date, fail handling if issuance delayed or cancelled.

**Repurchase agreement (repo) — overnight.** Sale of securities with simultaneous agreement to repurchase next business day. Custody operations: collateral delivery, cash receipt, accrued repo rate calculation, repurchase settlement next business day. Settlement methods: tri-party (custodian-administered), bilateral (direct counterparty), DvP-3 (multilateral net) where applicable.

**Repo — term.** Multi-day repurchase agreement. Custody operations: collateral delivery, cash receipt, mark-to-market and substitution rights through term, accrued repo rate calculation, repurchase settlement at term end. Failure modes include counterparty downgrade mid-term (substitution or unwind), collateral haircut adjustment, early termination on credit events.

**Repo — tri-party.** Repo administered by a tri-party agent (typically BNY Mellon or JPMorgan in the US) who manages collateral selection, substitution, and valuation. Custody operations: tri-party agent instruction, collateral pool management, automatic substitution per pre-agreed eligibility, daily mark-to-market.

**Repo — bilateral.** Direct counterparty repo without tri-party agent. Custody operations: direct collateral delivery, direct cash receipt, manual margin and substitution management.

**Repo — General Collateral (GC) versus specials.** GC repo uses any eligible collateral within a defined pool; specials repo uses specific securities (often "on special" because they are scarce). Different operational mechanics for collateral selection and pricing.

**Reverse repo.** Buy securities with simultaneous agreement to sell back. Custody operations are the mirror of repo: collateral receipt, cash payment, accrued interest receipt, securities return at term end.

**Buy-sell-back.** Economic equivalent of repo structured as separate buy and sell transactions. Custody operations similar to repo but with different legal and accounting treatment.

**Coupon strip and reconstitution.** Treasury STRIPS operations — separating a Treasury bond into individual interest and principal components, or reconstituting components into a whole bond. Custody operations: instruction processing, security exchange, position update.

**Mortgage-backed security (MBS) operations.** TBA (To Be Announced) trading, pool selection at settlement, factor adjustments for principal payments, monthly P&I distribution processing. MBS custody operations are operationally distinct from corporate bond custody due to the pass-through structure.

### FX (Foreign Exchange)

**Spot.** FX trade settling in standard convention (typically T+2 for major pairs, T+1 for USD/CAD, T+0 for some emerging markets). Custody operations: trade capture, currency position update, settlement via PvP through CLS or correspondent banking, reporting.

**Forward.** FX trade settling at agreed future date. Custody operations: trade capture, mark-to-market through term, settlement on value date.

**Non-Deliverable Forward (NDF).** FX forward settled in cash (typically USD) rather than deliverable currency. Used for restricted-currency exposures (CNY, KRW, BRL, INR, others). Custody operations: trade capture, fixing date determination, cash settlement of fixing-rate differential.

**FX swap.** Combination of spot and forward in opposite directions, used for funding or hedging. Custody operations: combined trade capture, two-leg settlement.

**FX option.** Currency option (call or put). Custody operations: premium settlement, ongoing mark-to-market, exercise or expiry processing, delivery on exercise.

**Settlement methods for FX:** PvP through CLS (Continuous Linked Settlement) for eligible currency pairs; on-us settlement when both legs are at the same bank; correspondent banking for non-CLS pairs; multi-leg roll for forward extensions.

### Derivatives

**Listed derivatives — futures.** Standardized exchange-traded futures contracts. Custody operations: trade capture, daily variation margin, exchange-cleared settlement, expiry processing (cash-settled or physical delivery).

**Listed derivatives — options.** Standardized exchange-traded options. Custody operations: premium settlement, daily mark-to-market, exercise or expiry processing, assignment for short positions, delivery on physical-settled exercise.

**OTC derivatives — give-up.** Trade executed by one broker but cleared and held at another (typically the custodian's prime broker). Custody operations: give-up instruction processing, position transfer, allocation handling.

**OTC derivatives — allocation.** Block trade executed at one counterparty allocated across multiple beneficial owner accounts. Custody operations: allocation instruction processing, per-account position update, per-account reporting.

**OTC derivatives — novation.** Existing OTC contract transferred from one counterparty to another (often to facilitate central clearing or counterparty risk management). Custody operations: novation instruction processing, contract termination at original counterparty, contract initiation at new counterparty, with continuity of economic terms.

**OTC derivatives — compression.** Multiple offsetting positions netted into smaller residual positions. Custody operations: compression cycle participation, position adjustment, regulatory reporting per EMIR / Dodd-Frank requirements.

**OTC derivatives — termination.** Early termination of an OTC contract by mutual agreement or contractual right. Custody operations: termination instruction, close-out valuation, settlement of close-out amount.

**OTC derivatives — exercise and assignment.** Option exercise and corresponding assignment. Custody operations: exercise instruction, delivery or cash settlement, position update.

**OTC derivatives — expiry processing.** Final settlement of expiring contracts. Custody operations: expiry valuation, cash settlement, position closure.

**Margin operations.** Initial margin (collateral posted at trade inception), variation margin (daily mark-to-market collateral), margin call processing (additional collateral demand on adverse mark), close-out (forced position closure on margin failure). Settlement methods: cash, securities collateral, tri-party administered margin, central clearing party (CCP) margin.

### Funds (Mutual Funds, ETFs, Hedge Funds, Private Equity, Private Credit)

**Subscription.** Beneficial owner subscribes to fund interests. Custody operations: subscription instruction processing, cash settlement to fund, position recording, regulatory reporting.

**Redemption.** Beneficial owner redeems fund interests. Custody operations: redemption instruction, cash receipt at redemption price, position retirement, regulatory reporting.

**Exchange.** Beneficial owner exchanges between funds in the same family (typical mutual fund operations). Custody operations: simultaneous redemption and subscription, no net cash if same-day same-family exchange.

**In-kind subscription.** Subscription paid in securities rather than cash (typical ETF creation, some hedge fund subscriptions). Custody operations: securities delivery to fund custodian, fund unit receipt, valuation reconciliation.

**In-kind redemption.** Redemption paid in securities rather than cash (typical ETF redemption, some hedge fund redemptions). Custody operations: fund unit delivery, securities receipt from fund custodian, valuation reconciliation.

**Capital call.** Private fund (private equity, private credit, real estate, venture) calls committed but undrawn capital from limited partners. Custody operations: capital call notice processing, cash payment to fund, commitment tracking update.

**Distribution.** Private fund distributes proceeds to limited partners. Custody operations: distribution receipt, cash or in-kind distribution processing, position adjustment.

**Side pocket.** Private fund segregates illiquid or distressed assets into separate accounting structure. Custody operations: side pocket creation, position transfer, separate valuation tracking, eventual realization processing.

**Gating and suspension.** Fund restricts redemptions due to liquidity, market stress, or other circumstances. Custody operations: gate or suspension notification, redemption queue management, beneficial owner notification, eventual processing when gate or suspension lifts.

**Money market fund operations.** Constant NAV (CNAV) versus floating NAV (FNAV) handling, liquidity fee imposition, gate imposition, sweep operations. Aureon's MMF infrastructure (per Grid 3 operational deployment, dual-lane FIAT and Digital infrastructure) operationalizes MMF custody at the framework level.

### Structured Products

**Subscription.** Initial purchase of structured product (note, certificate, structured deposit). Custody operations: trade capture, position recording, ongoing accrual tracking.

**Paydown.** Periodic principal repayment per structured product terms. Custody operations: paydown receipt, position adjustment, beneficial owner allocation.

**Call.** Issuer exercises call right on callable structured product. Custody operations: call notification, position closure, cash settlement at call price.

**Contingent acceleration.** Structured product accelerated payment due to triggering event (credit event, knockout barrier, performance threshold). Custody operations: triggering event confirmation, accelerated settlement processing.

**Restructuring.** Structured product terms modified by issuer or counterparty action (often in distress). Custody operations: restructuring notification, terms update, valuation adjustment, beneficial owner consent processing if required.

### Tokenized Securities

**Mint (issuance).** New tokenized securities created on-chain. Custody operations: mint transaction monitoring, position recording on-chain, beneficial owner allocation.

**Burn (retirement).** Tokenized securities destroyed on-chain (redemption, maturity, exchange). Custody operations: burn transaction execution or monitoring, position retirement, beneficial owner notification.

**On-chain transfer.** Tokenized security transferred between addresses on-chain. Custody operations: transfer execution, on-chain confirmation, off-chain books reconciliation.

**Atomic swap.** Simultaneous on-chain exchange of two tokens or token-versus-cash via smart contract. Custody operations: swap execution through Cato governance gate, atomic confirmation, position update across both legs.

**Smart contract execution.** Tokenized security operations executed through smart contract logic (automated coupon distribution, programmable transfer restrictions, embedded compliance logic). Custody operations: smart contract interaction monitoring, doctrine-over-code enforcement per Axiom 5, escalation when smart contract action conflicts with doctrine.

**Programmable distribution.** Smart contract executes scheduled or event-triggered distributions. Custody operations: distribution receipt monitoring, beneficial owner allocation, off-chain reporting reconciliation.

### Native Digital Assets

**Outright on-chain transfer.** Native digital asset moved between addresses. Custody operations: transaction signing under quorum authority for material magnitude, on-chain submission, confirmation monitoring, position update.

**Staking.** Native digital asset committed to consensus protocol in exchange for staking rewards. Custody operations: stake initiation, reward accrual tracking, slashing risk monitoring, unstake processing, return to liquid position.

**Unstaking.** Reversal of staking — withdrawal of staked assets. Custody operations: unstake instruction (often subject to network-level lock-up periods), confirmation monitoring, position return.

**Slashing.** Penalty applied to staked assets due to validator misbehavior or downtime. Custody operations: slashing event detection, position reduction, beneficial owner notification, root-cause analysis.

**Validator rewards.** Periodic distributions to staked positions. Custody operations: reward receipt, allocation to beneficial owners, tax treatment processing.

**DeFi protocol interaction.** Native digital assets deployed into decentralized finance protocols (lending, liquidity provision, yield farming). Custody operations: protocol interaction under quorum authority, smart contract risk evaluation, ongoing position monitoring, withdrawal processing. Doctrine-over-code per Axiom 5 binds: protocol-level actions that conflict with doctrine trigger Thifur-J hold and escalation.

**NFT operations.** Non-fungible token mint, transfer, sale, burn. Custody operations: each operation as on-chain transaction with custody-grade lineage; NFT-specific metadata tracking.

**Airdrops and token distributions.** Receipt of tokens distributed by protocol or project. Custody operations: airdrop receipt monitoring, position recording, evaluation of distributed asset (some airdrops are taxable events, some are spam tokens to ignore, some require active claim).

**Governance voting.** Token-holders vote on protocol governance proposals. Custody operations: voting instruction processing under beneficial owner direction, on-chain vote submission, proxy aggregation if multiple beneficial owners.

## Settlement Methods Taxonomy

Settlement methods are the operational mechanisms by which a custody operation completes. Different methods carry different settlement-risk profiles, counterparty exposures, and governance overlays. Custody under Aureon governance must handle all major settlement methods.

**DvP-1 (Delivery versus Payment, gross/gross).** Per BIS classification. Each securities transfer is settled gross against a corresponding cash transfer. Highest settlement-risk-mitigation profile because the linkage between securities and cash legs is per-trade. Used for high-value or high-risk settlements.

**DvP-2 (gross securities, net cash).** Securities transfers gross, cash settlements netted across multiple trades. Reduces cash settlement volume while maintaining per-trade securities settlement integrity. Used for active markets with frequent same-counterparty trading.

**DvP-3 (multilateral net).** Both securities and cash netted multilaterally. Highest operational efficiency but greatest exposure to settlement failure (gross failure of one party affects multilateral netting). Used in central counterparty (CCP) settled markets and some triparty arrangements.

**DvD (Delivery versus Delivery).** Security-for-security exchange without cash. Used in tokenized swaps, in-kind operations, and some securities lending arrangements.

**PvP (Payment versus Payment).** Used for FX settlement. Two cash legs settled simultaneously to eliminate Herstatt risk. CLS is the dominant PvP mechanism for major currency pairs.

**FoP (Free of Payment).** Securities transfer without cash component. Used for in-kind transfers, gifts, error corrections, and some collateral movements. Highest settlement-risk profile because no per-trade cash settlement; counterparty trust required.

**Atomic settlement.** Single irreversible operation, typically on-chain. Securities and cash legs settle simultaneously through smart contract execution. Eliminates settlement-risk window structurally. Available today on tokenized rails (Ethereum L1, Base, Arbitrum, Solana per Cato); anticipated for wholesale infrastructure (PORTS-aligned).

**Conditional settlement (when-issued, subject-to, contingent).** Settlement contingent on a future event: actual issuance for when-issued trading, regulatory approval for some M&A scenarios, performance conditions for some structured products. Custody operations track the conditional state and execute settlement when condition is satisfied or unwind when condition fails.

**Triparty settlement.** Custodian or specialized agent (BNY Mellon TriParty, JPMorgan Collateral Management, Euroclear Triparty, Clearstream Triparty) intermediates between principals to manage collateral selection, substitution, valuation, and operational mechanics. Used extensively for repo, securities lending, and OTC derivative collateral.

**Bilateral settlement.** Direct settlement between two principals without an intermediary. Used for some repo, securities lending, and OTC operations where the principals have direct relationships and operational capability.

**CCP-cleared settlement.** Settlement through a central counterparty that becomes the buyer to every seller and seller to every buyer. Eliminates bilateral counterparty risk. Used for listed derivatives, some OTC derivatives (post-Dodd-Frank clearing mandates), and an increasing share of repo (FICC sponsored membership and agent clearing).

## Lifecycle and Exception Handling

Custody operations include lifecycle stages and exception scenarios that the doctrine must explicitly govern. The enumeration below names the major exception categories; operational specifications detail handling per category.

**Failed trade — buy-in.** Failure to deliver securities triggers a forced purchase (buy-in) by the counterparty at prevailing market price, with the failing party bearing the cost differential. Custody operations: fail tracking, buy-in initiation per contractual or regulatory triggers (CSDR settlement discipline regime in EU, Treasury fails charge in US), cost settlement.

**Failed trade — sell-out.** Failure to receive securities triggers a forced sale (sell-out) by the counterparty. Custody operations are the mirror of buy-in.

**Partial settlement.** Trade partially settles when full quantity is unavailable. Custody operations: partial position update, residual fail tracking, eventual completion or cancellation processing.

**Trade cancellation.** Trade voided post-execution. Custody operations: cancellation instruction processing, position reversal, cash reversal, regulatory reporting amendment.

**Trade rebooking.** Trade modified post-execution (counterparty change, quantity adjustment, price correction). Custody operations: original trade reversal, replacement trade booking, lineage stamping linking original and replacement.

**Settlement timing variants.** T+0 (same-day), T+1 (next business day, US standard post-2024), T+2 (two business days, some international), T+3 (legacy), atomic (simultaneous on-chain). Custody operations adapt to timing per market and per asset class.

**Cross-border settlement complications.** Time zone differences, holiday mismatches, currency conversion requirements, jurisdictional restrictions. Custody operations: jurisdictional attribution per Verana, FX bundling where required, holiday calendar reconciliation.

**Corporate action exception scenarios.** Tender failure (insufficient acceptance), exchange rejection (consideration unavailable), rights expiration without exercise, conversion under reorganization terms, default and bankruptcy proceedings affecting custodied securities.

## Pledged-Asset Transaction Variety

Pledged-asset operations have their own transaction-type variety beyond what the object inventory addresses. Each is enumerated for explicit doctrinal treatment.

**Initial pledge.** New encumbrance created on previously-unpledged assets. Custody operations: pledge instruction processing, lien recording, encumbrance flag on custodied assets, beneficial owner consent confirmation.

**Substitution.** Replacement of pledged assets with different assets of equivalent value. Custody operations: substitution instruction, value verification, lien transfer to new assets, original assets released.

**Partial release.** Portion of pledged assets released from encumbrance. Custody operations: release instruction validation, value verification (remaining pledge sufficient), lien adjustment, partial release execution.

**Full release.** All pledged assets released from encumbrance. Custody operations: release instruction validation, lien removal, encumbrance flag clearance.

**Lien upgrade.** Existing junior lien promoted to senior lien position. Custody operations: lien priority adjustment, recording update, beneficial owner notification.

**Lien subordination.** Existing senior lien subordinated to a new senior lien. Custody operations: subordination agreement processing, lien priority adjustment, multi-creditor coordination.

**Cross-collateralization.** Same assets pledged to multiple obligations or multiple counterparties. Custody operations: multi-pledge tracking, priority management among pledgees, coordinated release processing on satisfaction of underlying obligations.

**Rehypothecation.** Pledgee re-pledges the assets to a third party (typical in prime brokerage and securities lending). Custody operations: rehypothecation tracking, beneficial owner consent confirmation per applicable regulatory regime (Reg T limits in US, Client Money Rules in UK), recovery in the event of pledgee insolvency.

**Reverse rehypothecation.** Tracking and recovery of rehypothecated assets when the original pledge is satisfied. Custody operations: recovery instruction, pledgee coordination, return processing.

**Prime brokerage margin.** Standardized margin operations under prime brokerage agreements. Custody operations: margin calculation, collateral posting, daily mark-to-market, margin call processing.

**OTC derivative collateral.** Bilateral collateral management for OTC derivatives. Custody operations: ISDA Credit Support Annex (CSA) implementation, collateral exchange, dispute resolution.

**CCP margin (initial and variation).** Margin posting to central clearing party. Custody operations: CCP margin calculation per CCP methodology, collateral posting, daily variation margin processing, default fund contributions.

**Exchange-traded derivative margin.** Margin for listed derivatives. Custody operations: clearinghouse margin processing, daily variation, expiry processing.

**Central bank facility collateral.** Collateral pledged to central bank lending facilities (Fed Discount Window, ECB Marginal Lending Facility, BOE Standing Facilities). Custody operations: facility-specific collateral eligibility, pre-positioning, draw and repayment processing.

## Architectural Implication: Comprehensive Coverage as Doctrine Standard

The enumeration above is comprehensive, not exhaustive. There will always be transaction types and settlement methods that fall outside the named categories — institutional custody is operationally evolving, and new instrument types, new settlement infrastructures, and new regulatory regimes will introduce new variants. The doctrine commits not to a closed list but to an architectural principle: custody under Aureon governance handles the variety, with the appropriate governance overlay for each transaction type and settlement method.

Operational specifications for Sovereign and Federate (`AUR-CUSTODY-INST-001`, `AUR-CUSTODY-FED-001`) are the documents that operationally enumerate which transaction types and settlement methods each product supports at deployment, what the per-type operational mechanics are, and what the per-type governance overlay looks like. The foundation doctrine establishes the commitment; the product specifications detail the implementation.

This architectural commitment matters competitively. Incumbent custody platforms typically support a broad transaction-type universe through accumulated operational specialization over decades, but the support is fragmented across specialized teams and bolt-on systems with separate audit surfaces. Custody under Aureon governance offers the same breadth with unified DSOR audit, unified CAOM-001 authority routing, and unified inherent-safety architecture across all transaction types. That is the structural advantage the doctrine establishes by committing comprehensively to the variety rather than addressing it incrementally.

---

# VI. CUSTODY-SPECIFIC ROLES IN THE AUREON ASSET-SERVICES WORKFORCE

The canonical doctrine v1.5 (Section IV) specifies an eleven-role workforce at three tiers (Thifur-R Ranger, Thifur-J JTAC, Thifur-H Hunter-Killer) under the historical "eFICC workforce" framing — eFICC standing for electronic Fixed Income, Currencies, and Commodities. The framing was correct for the canonical's scope at v1.5 because the doctrinal coverage at that time concentrated on post-trade operations across fixed income, currency, and commodity asset classes. With v1.6 substantively expanding the doctrine to encompass custody under Aureon governance across the full asset-class universe established in Section III, the workforce framing must expand correspondingly.

This doctrine renames the workforce from "eFICC workforce" to **Aureon Asset-Services Workforce**. The rename reflects three doctrinal realities:

**One — the asset-class universe is broader than eFICC.** eFICC encompasses fixed income, currencies, and commodities. The asset-class universe Section III commits to includes equities, real estate and real assets, insurance and reinsurance, intellectual property, trade finance, tokenized representations of all asset classes, native digital assets, alternative and specialty assets (art, wine, litigation finance, royalty streams), and emerging asset categories. The workforce must operate across this full breadth, not just the eFICC subset.

**Two — the operational surface is broader than post-trade.** eFICC framing implies post-trade operations as the primary work. Custody under Aureon governance includes pre-trade compliance, settlement, asset servicing (corporate actions, income, proxy), collateral management, reporting, and the Asset Services adjacencies named in the segmentation work (escrow, IPA, fund administration, structured credit). The workforce framing must accommodate the broader operational surface that Aureon Asset Services as a strategic positioning encompasses.

**Three — the strategic positioning is Aureon Asset Services, not Aureon eFICC.** The Asset Services roadmap (custody → escrow → IPA → fund administration → structured credit re-onboarding → structured credit new issue) defines the framework's commercial trajectory. The workforce framing should match the strategic posture rather than carry the historical eFICC label that bounded earlier doctrine work.

The rename is operational, not architectural. The existing role names remain correct at the function level — Settlement Operations is still Settlement Operations, Trade Support is still Trade Support, Reconciliation is still Reconciliation, Regulatory Reporting is still Regulatory Reporting. What changes is the workforce-level framing and the implicit scope each role operates across. A Settlement Operations Analyst in the Aureon Asset-Services Workforce handles settlement across equities, fixed income, FX, derivatives, funds, commodities, real estate, tokenized representations, native digital assets, and the emerging asset categories — not just within eFICC.

The four Tier 1 (Ranger) agents — Settlement Operations Analyst, Trade Support Analyst, Reconciliation Analyst, Regulatory Reporting Analyst — handle the operational core of asset-services workflows under R-class deterministic guardrails. This section adds the custody-specific roles to the workforce, anticipated in the segmentation doctrine as forthcoming work.

## New Custody-Specific Roles

Three new roles are added to the Aureon Asset-Services Workforce specifically for custody operations. Each operates within the appropriate canonical tier (R, J, or H) under the same guardrails as existing roles in that tier.

### Custody Operations Analyst (Tier 1 — Thifur-R)

The Custody Operations Analyst handles the deterministic procedural work of custody across the full asset-class universe: safekeeping records maintenance for traditional securities and alternative assets, settlement instruction processing for custody-side handling across all asset classes, corporate action processing per beneficial owner elections or defaults, income collection and disbursement (coupons, dividends, distributions, royalties, staking rewards, rental income from real estate interests), proxy material distribution and vote aggregation. Operations are R-class deterministic — no path selection, no settlement without DSOR confirmation, immediate escalation on discrepancy, immutable lineage stamped at execution.

The role is a peer to the Settlement Operations Analyst, Trade Support Analyst, Reconciliation Analyst, and Regulatory Reporting Analyst. Together the five Tier 1 agents handle the procedural-execution surface of asset-services operations across the full asset-class universe.

### Collateral Operations Specialist (Tier 2 — Thifur-J)

The Collateral Operations Specialist handles pledged-asset operations within Tier 2 bounded autonomy across the full asset-class universe — pledged equities, pledged fixed income, pledged commodities (including physical commodities at qualified storage facilities), pledged real estate interests, pledged digital assets, pledged tokenized assets, and pledged interests in any other asset category Aureon custodies. Collateral operations are Tier 2 rather than Tier 1 because they involve path selection within doctrinally-approved options — for example, choosing among eligible substitution collateral when a margin call requires repositioning, or selecting the appropriate routing for a multi-jurisdictional encumbrance change, or coordinating physical-commodity pledge documentation across qualified storage facilities and lien jurisdictions.

J-class guardrails apply: approved paths only (the Specialist selects from Kaladan-defined collateral routing options, never generates new); doctrine over code (smart-contract collateral logic does not override doctrine); no release without approval lineage; eligibility before routing; jurisdictional attribution before execution.

For pledged-asset operations of material magnitude that require quorum authority per Section VII, the Specialist's role is to assemble the operation package and route it to the quorum authority structure for approval — the Specialist does not execute material-magnitude operations on single-authority approval.

### FIAT Operations Specialist (Tier 2 — Thifur-J)

The FIAT Operations Specialist handles FIAT-leg operations within Tier 2 bounded autonomy. The role exists in 1:1 parity with the Digital Asset Custody Specialist below, recognizing that FIAT-leg operations across the asset-class universe involve the same path-selection complexity that digital-leg operations do, and require the same Tier 2 J-class bounded autonomy treatment. The doctrine commits to structural symmetry between FIAT and digital legs because beneficial owners increasingly hold positions across both representations of the same asset class (FIAT-held Treasuries alongside tokenized Treasuries, FIAT-held money market positions alongside tokenized cash via stablecoin, FIAT-held fund interests alongside tokenized fund interests). The framework does not privilege one leg over the other architecturally.

The FIAT Operations Specialist's path-selection scope spans:

**Multi-currency settlement rail routing.** Selection among Fedwire (US large-value), CHIPS (US clearing), ACH (US batch), SWIFT MT103 / MT202 (international correspondent), Target2 (Eurozone), CHAPS (UK), Zengin (Japan), and analogous large-value and clearing systems globally. Routing decisions consider settlement urgency, finality requirements, fee economics, counterparty correspondent banking arrangements, and operational hours of each system.

**Correspondent banking coordination.** Selection of correspondent bank routing for jurisdictions where direct large-value system access is impractical. Coordination of nostro and vostro account positioning, cover payment versus serial payment selection, intermediary bank routing decisions where multiple correspondents are eligible.

**Cross-border settlement with FX leg coordination.** Sequencing of FX execution and securities settlement when the trade requires currency conversion. Selection among CLS PvP settlement, on-us settlement when both legs are at the same correspondent, bilateral PvP arrangements, and traditional gross settlement when PvP is unavailable.

**Depository versus sub-custodian routing.** For jurisdictions where Aureon-governed custody can access either direct depository membership or sub-custodian intermediation, the routing decision involves operational efficiency, counterparty risk concentration, jurisdictional regulatory compliance, and cost economics.

**Large-value payment system selection.** When multiple eligible large-value systems can settle a payment of material magnitude, the Specialist selects among them based on settlement risk profile (Fedwire is gross-real-time-final; CHIPS uses bilateral and multilateral net with finality at end of day; SWIFT correspondent depends on correspondent bank operational status), counterparty preferences, and operational considerations.

**Fed-related operations.** Discount window borrowing collateral coordination, Standing Repo Facility operations, Reverse Repo Facility coordination, Federal Reserve account operations for entities with direct access. These operations involve path selection within Fed-defined eligible operations and require dedicated Tier 2 specialist handling.

**Cash sweep and short-term investment routing.** Selection of cash sweep destinations across MMFs (constant NAV and floating NAV, government and prime), bank deposit programs, repo investment vehicles, and tri-party repo arrangements. Routing considers yield, operational cutoffs, redemption mechanics, and risk concentration.

J-class guardrails apply with FIAT-leg-specific rendering: approved paths only (the Specialist selects from Kaladan-defined FIAT routing options, never generates new); doctrine over code (FIAT settlement system message logic does not override doctrine — for example, an automated correspondent banking instruction that conflicts with doctrine triggers Thifur-J hold and escalation); no settlement without approval lineage; eligibility before routing (KYC/KYB, OFAC screening, sanctions checks, correspondent bank compliance verification before any large-value transfer); jurisdictional attribution before execution (cross-border FIAT transfers must be jurisdictionally attributed via Verana per canonical Section VIII).

Material-magnitude FIAT operations (large-value transfers above thresholds defined in operational specifications, cross-border settlements involving sanctioned-jurisdiction adjacency, correspondent banking changes affecting custody routing) are quorum authority operations per Section VII. The Specialist's role is to assemble and route, not to execute material-magnitude operations on single-authority approval.

### Digital Asset Custody Specialist (Tier 2 — Thifur-J)

The Digital Asset Custody Specialist handles native digital asset operations and tokenized-asset operations within Tier 2 bounded autonomy. The role is Tier 2 rather than Tier 1 for the same reason as the Collateral Operations Specialist: digital asset operations involve path selection (choice of settlement rail through Cato, choice of signing ceremony participants, choice of transaction batching, choice of bridge or atomic-swap mechanism for cross-chain operations) that exceeds Tier 1 R-class scope but remains within Tier 2 J-class bounded autonomy.

J-class guardrails apply with digital-asset-specific rendering: approved paths only (the Specialist selects from Cato-validated rails); doctrine over code (smart-contract execution does not override doctrine, including DeFi protocol interactions); no release without approval lineage; eligibility before routing (KYC/KYB, OFAC screening, sanctions checks before any on-chain transaction); jurisdictional attribution before execution (cross-border digital asset transfers must be jurisdictionally attributed via Verana per canonical Section VIII).

Material-magnitude native digital asset operations are quorum authority operations per Section VII. The Specialist's role is to assemble and route, not to execute on single-authority approval.

## Anticipated Additional Asset-Class-Specific Roles

The asset-class universe in Section III commits the framework to operational coverage across categories that may require dedicated specialist roles beyond the three added in this doctrine. The doctrine names these as anticipated work for subsequent doctrine versions or product-specific operational specifications:

**Physical Commodity Custody Specialist (Tier 2 — Thifur-J).** Handles physical commodity custody operations: precious metals at LBMA-approved vaults, base metals at LME warehouse locations, energy commodities in storage, agricultural commodities. Path selection includes vault routing, jurisdictional warehouse selection, allocated versus unallocated structure choice, insurance coverage coordination.

**Real Asset Custody Specialist (Tier 2 — Thifur-J).** Handles real estate, infrastructure, and natural resource asset custody. Path selection includes title custody structure (DST, TIC, partnership interest, deed in trust), jurisdictional recording requirements, lien priority management for real estate-backed lending, royalty distribution mechanics for natural resource interests.

**Alternative Asset Custody Specialist (Tier 2 — Thifur-J).** Handles art, wine, collectibles, IP and royalty stream custody. Path selection includes qualified storage facility selection (museum-grade for art, professional cellaring for wine), authentication and provenance verification protocols, royalty stream payment processing across distribution networks.

**Insurance and ILS Custody Specialist (Tier 2 — Thifur-J).** Handles insurance contract custody and insurance-linked securities (catastrophe bonds, longevity bonds, sidecars). Path selection includes regulatory framework navigation (NAIC, state insurance commissioner requirements, Bermuda monetary authority for offshore reinsurance), trigger event monitoring for ILS, settlement coordination for insurance claim events.

These roles are not added in this v1.0 because the operational specifications for Sovereign and Federate (`AUR-CUSTODY-INST-001`, `AUR-CUSTODY-FED-001`) will determine which asset-class specialist roles each product deploys at launch versus deferred to subsequent expansion. The architectural commitment is that the workforce can extend to cover the full asset-class universe; the operational specifications detail the per-deployment role population.

## Workforce Structure After Custody Additions

| Tier | Class | Existing Roles (canonical v1.5, framework-level) | Added Roles (this doctrine) | Anticipated Future Roles |
|---|---|---|---|---|
| Tier 1 | Thifur-R (deterministic) | Settlement Operations Analyst, Trade Support Analyst, Reconciliation Analyst, Regulatory Reporting Analyst | Custody Operations Analyst | (none anticipated at Tier 1 — deterministic surface is bounded) |
| Tier 2 | Thifur-J (bounded autonomy) | (compliance, surveillance, risk, AML/KYC per canonical) | Collateral Operations Specialist, FIAT Operations Specialist, Digital Asset Custody Specialist | Physical Commodity Custody Specialist, Real Asset Custody Specialist, Alternative Asset Custody Specialist, Insurance and ILS Custody Specialist |
| Tier 3 | Thifur-H (adaptive) | (per canonical) | (no custody-specific Tier 3 roles in this doctrine) | Custody Risk Manager, Asset-Class Concentration Manager, Custody Data Governance Manager |

The expanded workforce is the **Aureon Asset-Services Workforce**. The eFICC framing is retired at the foundation doctrine level, with the Aureon Asset-Services Workforce framing replacing it. The FIAT Operations Specialist and Digital Asset Custody Specialist are explicitly named in 1:1 parity at Tier 2 — the doctrine does not privilege one leg over the other. The architectural commitment is that beneficial owner positions held across both FIAT and digital representations of the same asset class are governed with structural symmetry, with neither leg treated as the implicit default. Subsequent doctrine work may add Tier 3 asset-services-specific roles (Custody Risk Manager handling adaptive monitoring of concentration risk across asset classes, Asset-Class Concentration Manager monitoring concentration limits across the full asset-class universe, Custody Data Governance Manager handling data lineage for custody data across asset classes) but those are anticipated work, not part of this v1.0 specification.

## Operational Implication for Sovereign and Federate

`AUR-CUSTODY-INST-001` (Sovereign) will deploy the full expanded workforce because Sovereign is institutional displacement and the licensee runs the entire custody operation. `AUR-CUSTODY-FED-001` (Federate) will deploy a subset because Federate is governance overlay above existing custodians — the existing custodians perform the operational work, and Aureon deploys agents that govern across them rather than execute the underlying operations. The Federate-specific workforce will be specified in `AUR-CUSTODY-FED-001`; the framework here establishes that the workforce *exists* and is doctrinally defined at the foundation level. Each product's operational specification details which asset-class-specific specialist roles are deployed at launch and which are deferred.

---

# VII. QUORUM AUTHORITY OPERATIONAL SPECIFICATION

The canonical doctrine v1.5 Section VI defined quorum authority as a future-mode primitive: *"A quorum authority operation is one that cannot be authorized by any single tier of the CAOM authority structure — including Tier 3 — and instead requires N-of-M independent signatures from authorities with separation of duties enforced architecturally rather than procedurally."* The canonical further established that *"the detailed quorum authority specification — the N-of-M selection per operation class, the separation-of-duties enforcement mechanism, the signature ceremony protocol, the architectural enforcement of independence between signing authorities — is the work of v1.6 (custody)."*

This section delivers that operational specification for custody operations.

## When Quorum Authority Applies to Custody

Quorum authority applies to custody operations meeting any of the following criteria:

**Material magnitude.** Custody operations involving asset values, position changes, or counterparty exposures above thresholds defined in operational specifications (the specific thresholds are Sovereign- and Federate-specific and will be set in `AUR-CUSTODY-INST-001` and `AUR-CUSTODY-FED-001` respectively).

**Pledged-asset encumbrance changes.** Lien releases, encumbrance modifications, collateral substitutions on actively-margined positions, and pledge terminations regardless of magnitude. The unrecoverable failure modes (releasing collateral to the wrong party, failing to update encumbrance records) make these operations quorum-required by category, not by magnitude.

**Native digital asset transactions.** All on-chain transactions transferring native digital assets out of Aureon-governed custody (transactions internal to a custody account, such as protocol staking that returns to the same custody account, may be exempt per operational specification). The unrecoverable failure modes (finality, key compromise, smart-contract interaction risk) make these operations quorum-required by category.

**Key ceremonies.** Generation of new private keys, rotation of existing keys, recovery operations, and any ceremony involving direct key material handling. Quorum required by category regardless of asset magnitude.

**Cold storage operations.** Movement of assets into or out of cold storage, including any operation requiring physical access to key material custody. Quorum required by category.

**Custodian-of-custodian operations.** Federate-specific case: operations where Aureon (as governance overlay) directs an underlying custodian to take action affecting beneficial owner assets. Quorum required by category because the action is taken on behalf of beneficial owners through an intermediary, increasing failure-mode complexity.

The list is intentionally specific. Quorum authority is operationally heavier than single-authority approval — it requires multiple independent signers, signature ceremonies, and architectural separation-of-duties enforcement. Applying it where it is not required would impose unnecessary operational friction on routine custody operations. Applying it where required is the architectural answer to the unrecoverable failure modes Axiom 10 governs.

## N-of-M Structure

The default quorum authority structure is **3-of-5 independent signatures** for material custody operations. The specific N-of-M may be tightened (4-of-5, 4-of-6, 5-of-7) for higher-magnitude operations or relaxed (2-of-3, 2-of-4) for lower-magnitude operations within the quorum-required category, per operational specification in Sovereign and Federate documents.

The independence requirement is architectural, not procedural. The five signing authorities in a 3-of-5 structure must satisfy:

**Identity independence.** No single human individual may hold more than one signing authority position. A single individual cannot satisfy multiple positions through multiple credentials or roles.

**Organizational independence.** At Sovereign deployment, the five signing authorities should span at least three organizational units (for example: operations, risk, compliance, treasury, audit). At Federate deployment with smaller organizational structures, the requirement adapts but architectural separation must be demonstrable to regulators.

**Geographic independence (where feasible).** For operations involving asset categories where physical or jurisdictional dispersion is feasible, signing authorities should span at least two jurisdictions. This protects against single-jurisdiction failure modes (regulatory action, physical incident, political event affecting one location).

**System independence.** The signing infrastructure for each authority must be architecturally separated — independent credentials, independent signing devices, independent authentication infrastructure. A compromise of any single signing system must not be sufficient to forge multiple signatures.

**Temporal independence (for high-magnitude operations).** For operations above operational-specification thresholds, signatures must be collected over a defined minimum interval (for example, 1 hour minimum between first and last signature) to allow detection of anomalous signing patterns. This protects against rapid-fire compromise scenarios.

## Signature Ceremony Protocol

A quorum authority signature ceremony for a custody operation proceeds in defined steps:

**Step 1 — Operation package assembly.** The Tier 2 specialist (Collateral Operations Specialist or Digital Asset Custody Specialist as appropriate) assembles the complete operation package: the custody operation specification, the affected beneficial owner identifications, the asset identifications, the doctrine version stamp, the pre-operation DSOR state, the post-operation projected DSOR state, and the supporting documentation (counterparty instructions, regulatory authorizations, beneficial owner approvals if required by mandate).

**Step 2 — Ceremony initiation.** The operation package is submitted to the quorum authority infrastructure (specified by Sovereign or Federate operational documents — typically a multi-signature wallet for digital asset operations, a multi-signature ceremony platform for traditional operations). The ceremony is initiated with a session identifier that is logged to the DSOR.

**Step 3 — Signature collection.** Each signing authority independently reviews the operation package, performs their independent verification (per their organizational responsibility), and signs the package. Each signature is logged to the DSOR with the authority identity, the timestamp, and any commentary the signer attaches.

**Step 4 — Quorum verification.** When the N-of-M threshold is reached, the quorum authority infrastructure verifies that all required independence criteria are satisfied (no single signer fulfilled multiple positions, organizational and geographic distribution per requirement, system independence per requirement, temporal distribution per requirement for high-magnitude operations). Verification failure halts the ceremony and escalates to operator review per CAOM-001 Tier 0 Halt protocol.

**Step 5 — Operation execution.** Upon successful quorum verification, the custody operation executes through the appropriate Tier 1 or Tier 2 agent. The execution is itself logged to the DSOR with the quorum ceremony lineage attached.

**Step 6 — Post-operation reconciliation.** The post-operation DSOR state is verified against the projection from Step 1. Any discrepancy triggers immediate escalation per Axiom 6 escalation completeness.

The ceremony protocol is designed to make undetected compromise of the signing process architecturally implausible. Every step is logged, every authority is independently verified, every reconciliation is explicit. The DSOR record produced by a complete ceremony is the institutional-grade audit artifact that custody operations of material magnitude require.

## Inherent-Safety Status of Custody Surfaces Under Quorum Authority

Per canonical Axiom 10, custody surfaces requiring quorum authority are declared inherent-safety surfaces. The quorum architecture above is the architectural implementation of inherent-safety for these surfaces: multiple independent simultaneous failures required to produce loss (compromise of N independent signing authorities simultaneously), each independently bounded (single-signer compromise insufficient), no single component or authority on the loss path (separation-of-duties enforced architecturally).

The doctrine claim is not that compromise is impossible. The doctrine claim is that the failure surface has been driven below the threshold of any plausible institutional risk-modeling framework, consistent with the canonical Axiom 10 definition of inherent-safety. A 3-of-5 quorum with full independence requirements requires three independent compromises to produce loss, each compromise itself bounded by the independence architecture. This is the architectural standard that custody operations of material magnitude require to be defensible to risk committees, rating agencies, regulatory examiners, and licensing counterparties.

---

# VIII. CUSTODY-SPECIFIC FAILURE-MODE TAXONOMY REFINEMENT

The canonical doctrine v1.5 Section VI established the three-class failure-mode taxonomy: RA (Recoverable Automatic), RM (Recoverable Manual), UR (Unrecoverable). The canonical further established that *"four classes (further subdividing unrecoverable into reversible-via-other-means and final) is custody-specific and will be introduced in v1.6 within the custody section, where the distinction between insurance-recoverable loss and final loss matters for licensee economics."*

This section delivers that refinement.

## Four-Class Taxonomy Within the Custody Domain

Within custody operations, the UR (Unrecoverable) class from the three-class taxonomy is refined into two sub-classes:

**UR-R — Unrecoverable but Reversible-via-Other-Means.** Loss that cannot be undone by subsequent custody operations but can be recovered through external mechanisms: insurance claims, indemnification by counterparties, regulatory reimbursement programs, beneficial owner indemnification, or industry-mutualized loss-sharing arrangements. The custody operation cannot itself undo the loss, but the licensee's economic exposure is bounded by external recovery mechanisms.

Examples across the asset-class universe:
- **Traditional securities:** settlement to an incorrect counterparty where the counterparty is identified and indemnification can be pursued; pledged-asset release where the counterparty's hold can be enforced through legal action; corporate action processed incorrectly where the beneficial owner is indemnified per custody agreement.
- **Physical commodities:** vault loss covered by Lloyd's-syndicated specie insurance (typical for LBMA-vault precious metals); LME warehouse incident covered by warehouse-keeper indemnification; agricultural commodity quality dispute resolved through arbitration with insurance backstop.
- **Real estate and real assets:** title dispute resolved through title insurance claim; rental income misallocation recoverable through property manager indemnification; infrastructure asset operational interruption covered by business interruption insurance.
- **Insurance and ILS:** counterparty default on insurance contract recoverable through state guaranty association or reinsurance backstop; ILS trigger event misclassification correctable through arbitration mechanism with policy backstop.
- **IP and royalty streams:** royalty calculation error recoverable through audit and clawback mechanisms in the licensing agreement; counterparty payment default on royalty stream recoverable through enforcement of collateral or indemnity provisions.
- **Trade finance:** letter of credit dispute resolved through ICC arbitration with bank standby commitment; receivables fraud covered by credit insurance; supply chain finance counterparty default recoverable through collateral enforcement.
- **Tokenized assets:** smart contract vulnerability exploitation recoverable through protocol-level insurance fund or issuer indemnification (when such mechanisms exist and are enforceable); tokenization issuer error correctable through reissuance with the issuer bearing economic loss.
- **Funds:** subscription or redemption error recoverable through fund-administrator indemnification; capital call processing error recoverable through subsequent reconciliation with bounded economic exposure.

The doctrine treatment of UR-R failures: incident response per canonical Section X, insurance and indemnification claim initiation, beneficial owner notification per disclosure obligations, root-cause analysis with doctrine update if applicable. The licensee's economic exposure is bounded; the operational and reputational exposure is real but recoverable over time.

**UR-F — Unrecoverable and Final.** Loss that cannot be undone by any operation (custody or external) — the asset or position is permanently impaired with no recovery mechanism available. The licensee's economic exposure is the full loss amount.

Examples across the asset-class universe:
- **Native digital assets:** on-chain transaction with finality to a wrong address where the receiving address is unrecoverable (compromised key, lost private key, smart-contract burn); private key compromise with active signing authority and no detection until after asset transfers occurred; bridge or atomic-swap counterparty failure with no recovery mechanism; DeFi protocol exploit with permanent fund loss.
- **Physical commodities:** physical asset destroyed in a security incident exceeding insurance coverage limits; precious metal vault loss where insurance is uninsured for the specific incident type (war, nuclear, certain natural disasters per typical specie policy exclusions); base metal warehouse fraud where insurance is voided due to misrepresentation.
- **Real estate and real assets:** title fraud where title insurance is voided or limits exhausted; environmental contamination liability exceeding all insurance and indemnification; mineral rights dispute resolved against beneficial owner with no recourse.
- **Insurance and ILS:** insurance carrier insolvency where state guaranty fund coverage is exhausted; ILS trigger event with disputed loss attribution and no successful recovery mechanism.
- **IP and royalty streams:** patent invalidation through subsequent litigation with no defensive insurance or indemnification recoverable; copyright loss through public domain dedication or successful infringement defense by counterparty; trademark abandonment.
- **Pledged collateral:** pledged collateral released to a counterparty that subsequently fails with no indemnification recoverable; key material compromise on quorum-authority-protected operations producing unauthorized release.
- **Tokenized assets:** smart contract vulnerability with no protocol insurance, no issuer indemnification, no enforceable recovery mechanism; tokenization issuer insolvency where the off-chain underlying asset cannot be recovered to beneficial owners.
- **Trade finance:** export receivable loss where credit insurance is voided or limits exhausted; documentary credit fraud with no recovery mechanism.

The doctrine treatment of UR-F failures: this is the failure mode Axiom 10 inherent-safety architecture exists to make architecturally impossible. UR-F failures on inherent-safety surfaces (custody surfaces requiring quorum authority) **must not be reachable**. If a UR-F failure occurs on an inherent-safety surface, this represents a doctrine integrity violation under Axiom 8 and triggers immediate Tier 0 Halt and full incident response per canonical protocols.

UR-F failures on non-inherent-safety surfaces (custody operations of non-material magnitude) are still doctrine concerns but do not trigger Axiom 10 violations. Treatment is the same as UR class in the three-class taxonomy: incident response, root-cause analysis, doctrine update if applicable.

## Why the Refinement Matters for Licensee Economics

The distinction between UR-R and UR-F is fundamental to the economics of custody as a licensable service. UR-R failures have bounded licensee economic exposure through insurance, indemnification, and external recovery mechanisms. The licensee's pricing of custody services can be calibrated against UR-R risk through actuarial modeling and reinsurance arrangements. UR-F failures have unbounded economic exposure (up to the asset value at risk) and cannot be priced against through standard mechanisms.

This is why the four-class taxonomy is custody-specific and was deferred from the canonical v1.5 to this doctrine: pre-custody, the three-class taxonomy was sufficient because the operations in scope did not produce material UR-F failure modes. Custody introduces categories of operations (key ceremonies, on-chain transactions, cold storage operations, large pledged-asset releases) where UR-F is possible without inherent-safety architecture. The four-class taxonomy makes the distinction explicit so that licensees can correctly assess their economic exposure and so that the doctrine can require inherent-safety architecture on the specific surfaces where UR-F is possible.

The operational implication: every custody operation type, in both Sovereign and Federate operational specifications, must be tagged with its failure-mode class (RA, RM, UR-R, UR-F). Operations tagged UR-F that are not on inherent-safety surfaces with quorum authority are doctrine integrity gaps and must be either remediated (move to inherent-safety surface with quorum authority) or eliminated (operation type is not offered).

---

# IX. INHERENT-SAFETY ARCHITECTURE FOR CUSTODY

Canonical Axiom 10 established inherent-safety as a doctrinal term: *"Where the doctrine declares a surface inherent-safety, the failure mode must be eliminated by design — multiple independent simultaneous failures required to produce loss, each independently bounded under stated assumptions."* The canonical further declared custody as the first inherent-safety addendum: *"Surfaces declared inherent-safety in this document or in any addendum (custody being the first such addendum, anticipated in v1.6) inherit the requirements of this axiom automatically."*

This section operationalizes Axiom 10 within the custody domain.

## Custody Surfaces Declared Inherent-Safety

The following custody surfaces are declared inherent-safety surfaces under Axiom 10. The list spans the full asset-class universe established in Section III, recognizing that inherent-safety requirements apply wherever UR-F failure modes are possible without architectural protection.

**Pledged-asset operations of material magnitude.** Per Section VII, these require quorum authority, and the quorum architecture is the inherent-safety implementation. Applies across all asset classes — pledged equities, pledged fixed income, pledged commodities (physical and financial), pledged real estate interests, pledged digital assets, pledged tokenized assets, pledged IP and royalty streams used as collateral.

**Native digital asset operations of material magnitude.** Per Section VII, these require quorum authority, and the quorum architecture is the inherent-safety implementation.

**Tokenized asset issuer operations.** Mint, burn, and supply control operations on tokenized representations of underlying assets. The unrecoverable failure mode (over-issuance, unauthorized burn, supply manipulation) affects all beneficial owners of the tokenized asset class and is severe by category, not by per-operation magnitude.

**Material-magnitude FIAT settlement operations.** Large-value FIAT transfers above operational-specification thresholds across Fedwire, CHIPS, Target2, CHAPS, SWIFT MT202 correspondent banking, and analogous large-value systems globally. The unrecoverable failure modes (transfer to wrong correspondent with subsequent counterparty failure, finality on wrong-beneficiary instruction in real-time gross settlement systems, settlement-system reversal disputes) parallel the unrecoverable failure modes on digital rails and require equivalent inherent-safety architecture. Quorum authority per Section VII applies in 1:1 parity with digital material-magnitude operations.

**Correspondent banking instruction integrity.** Operations that establish, modify, or terminate correspondent banking relationships affecting custody settlement routing. The unrecoverable failure modes (compromised correspondent instructions producing unauthorized routing, fraudulent SWIFT instructions on correspondent accounts, BIC/IBAN instruction integrity failures) require inherent-safety architecture. Multiple independent authorities, separation of correspondent-relationship management from settlement-instruction execution, and architectural verification of instruction integrity before correspondent-routed settlement.

**Depository membership operations.** Operations affecting Aureon-governed entities' membership status at central securities depositories (DTCC, Euroclear, Clearstream, JASDEC, and analogous depositories). Membership grants direct access to settlement infrastructure; unauthorized changes affect every beneficial owner whose assets settle through that depository. Inherent-safety architecture: multiple independent authorities, depository-level multi-signature requirements where supported, separation of membership administration from settlement operations.

**Large-value payment system finality operations.** Operations that depend on or produce settlement finality in real-time gross settlement systems (Fedwire, Target2, CHAPS) or end-of-day net settlement systems (CHIPS, ACH at Federal Reserve closing). Finality is the property that makes these systems valuable for institutional settlement; the same property makes failure modes severe — once final, a wrong-beneficiary transfer cannot be reversed by the settlement system itself. Recovery depends on counterparty cooperation or legal action, both of which fall under UR-R rather than RA classification. Material-magnitude operations on these surfaces are inherent-safety surfaces.

**FX bundled settlement operations.** Operations that bundle FX execution with securities settlement, or that depend on PvP settlement through CLS for the FX leg. The unrecoverable failure modes (Herstatt-style settlement risk if PvP fails, mismatched currency settlement, settlement-system holiday calendar conflicts producing partial-leg settlement) require inherent-safety architecture for material magnitude. Multi-currency settlement coordination is structurally complex enough that single-authority approval is insufficient at material magnitude.

**Key ceremonies.** Generation, rotation, recovery, and any direct key material handling operations across all cryptographic infrastructure (digital asset signing keys, tokenization issuer keys, multi-signature ceremony keys, threshold cryptography key shares).

**Cold storage operations.** Movement of assets into or out of cold storage. Applies to digital asset cold storage (hardware wallets, air-gapped systems) and to physical asset cold storage equivalents (vault entry for precious metals, warehouse access for high-value commodities, secured storage for art and collectibles).

**Custodian-of-custodian operations (Federate).** Operations where Aureon directs an underlying custodian to take action affecting beneficial owner assets across any asset class.

**Beneficial owner identity changes.** Operations changing the beneficial owner of record on a custody account (transfers between beneficial owners, beneficiary changes on trusts, changes in account ownership, changes in title for real estate or other titled assets, changes in royalty stream beneficial ownership). The unrecoverable failure mode (assets held under wrong beneficial owner identity) is severe regardless of asset class and requires inherent-safety architecture.

**Quorum authority enrollment changes.** Operations adding, removing, or modifying signing authorities in the quorum structure itself. Required by the meta-architectural principle that the inherent-safety mechanism's own integrity must be inherent-safety-protected.

**Physical commodity vault operations of material magnitude.** Movements of precious metals between LBMA-approved vaults, base metal allocation changes at LME warehouse locations, large-scale physical commodity title transfers. The unrecoverable failure modes (vault loss, unauthorized release, allocation fraud) require inherent-safety architecture analogous to digital asset key ceremony protections — multiple independent authorities, separation of custody and instruction roles, geographic and organizational independence in vault personnel.

**Real estate title operations.** Title transfer, lien recording, encumbrance changes affecting recorded title to real property. The unrecoverable failure modes (title fraud, recording errors with subsequent third-party reliance) require inherent-safety architecture: multiple independent authorities including the recording jurisdiction's title authority, title insurance coverage as part of the failure-mode boundary, separation of custody from title-recording functions.

**IP rights operations of material magnitude.** Patent assignments, trademark transfers, copyright registrations, royalty stream beneficial ownership changes for material IP portfolios. The unrecoverable failure modes (defective assignment, abandonment through inaction, infringement defense failure) require inherent-safety architecture: multiple independent authorities including IP counsel, separation of custody from IP prosecution functions, jurisdictional registration coordination.

**Insurance contract operations of material magnitude.** Policy ownership transfers, beneficiary changes, policy assignments for material insurance contracts (life settlements, structured settlements, longevity contracts). The unrecoverable failure modes (defective transfer, beneficiary fraud, insurance carrier compliance violations) require inherent-safety architecture: multiple independent authorities including the insurance carrier's authority verification, regulatory framework compliance checks, separation of custody from insurance contract administration.

**ILS trigger event determinations.** Catastrophe bond, longevity bond, and other ILS trigger event classifications. The unrecoverable failure modes (incorrect trigger determination affecting payment obligations to beneficial owners) require inherent-safety architecture: multiple independent verification authorities, calculation agent independence, dispute resolution architecture.

**Carbon credit and environmental commodity operations of material magnitude.** Registry-level operations on voluntary carbon market credits, compliance market allowances, RECs. The unrecoverable failure modes (double-counting, unauthorized retirement, registry fraud) require inherent-safety architecture: multiple independent authorities including registry verification, separation of custody from registry administration, jurisdictional regulatory coordination.

**Physical asset authentication and provenance operations.** Authentication, provenance verification, and material custody changes for art, wine, rare collectibles, and other authenticated alternative assets. The unrecoverable failure modes (authentication fraud, provenance disputes affecting marketability) require inherent-safety architecture: multiple independent authentication authorities, separation of custody from authentication functions, documented provenance chain integrity.

## Architectural Requirements on Inherent-Safety Surfaces

Per Axiom 10, inherent-safety surfaces require specific architectural properties:

**No single authority on the loss path.** No single human, no single agent, no single system, no single signature can produce loss. The quorum authority architecture specified in Section VII satisfies this for surfaces requiring quorum.

**No single component on the loss path.** No single piece of infrastructure (signing device, authentication system, network path, storage system) can produce loss through compromise. The independence requirements in Section VII Step 4 (system independence) satisfy this.

**No single signature on the loss path.** No single cryptographic signature can authorize loss-producing operations. The N-of-M structure in Section VII satisfies this with N ≥ 2 in all configurations and N ≥ 3 in default configuration.

**No single key on the loss path.** No single cryptographic key can authorize loss-producing operations. Multi-signature wallet architecture, multi-party computation (MPC) cryptography, and threshold signature schemes all satisfy this when configured to require multiple key holders.

**No single jurisdiction on the loss path.** No single regulatory or legal jurisdiction can produce loss through unilateral action. Geographic independence per Section VII satisfies this where operationally feasible.

**No single counterparty on the loss path.** No single counterparty (custodian, sub-custodian, settlement agent, vendor) can produce loss through unilateral action or failure. Multi-custodian arrangements, sub-custody diversification, and counterparty redundancy in critical paths satisfy this.

These six "no single" requirements collectively define inherent-safety architecturally. A custody surface satisfies inherent-safety when all six requirements are demonstrably met. Demonstration is the work of the operational specifications (Sovereign and Federate) and the licensee's deployment configuration; the doctrine establishes the requirements.

## What Inherent-Safety Does and Does Not Claim

Per the canonical Axiom 10 definition of inherent-safety, the doctrine does not claim that compromise is impossible. The doctrine claims that the failure surface has been driven below the threshold of any plausible institutional risk-modeling framework. Compromise remains possible at computationally bounded rates under stated assumptions, at multi-component independent failure rates under independence assumptions, at multi-jurisdiction simultaneous failure rates under geographic distribution assumptions.

The discipline matters. Marketing language may describe inherent-safety surfaces as "zero-fail" for buyer comprehensibility. Doctrine uses "inherent-safety" with the precise architectural meaning above. Where regulators, risk committees, or rating agencies engage with custody operations, the doctrine standard is the relevant standard — the architectural impossibility of single-point failure with multiple independent failures required for loss.

---

# X. FORWARD-STATE FRAMEWORK (5-10 YEAR HORIZON)

This section addresses the forward-state architecture for custody under Aureon governance over the 5-10 year horizon. The forward-state is real, not speculative — multiple of the trajectories named below are already in motion at multiple institutions, and the architectural prerequisites in the Aureon framework are positioned for all of them. The doctrine commits to the forward-state architecturally rather than waiting for full operational maturity at any single trajectory.

## FIAT Settlement-Rail Governance

The Aureon framework's commitment to multi-rail governance applies to FIAT settlement rails with the same structural rigor it applies to tokenized rails. The FIAT settlement landscape is itself multi-rail — Fedwire, CHIPS, ACH, SWIFT correspondent banking, Target2, CHAPS, Zengin, and analogous large-value, clearing, batch, and correspondent systems globally — and selection among them is itself a governance decision the framework treats as first-class architectural concern, not as a settled operational default.

The doctrine commits FIAT settlement-rail governance to operate in 1:1 parity with tokenized settlement-rail governance. Custody operations under Aureon governance query a FIAT-rail equivalent of the Cato governance gate before material-magnitude FIAT settlements. The gate evaluates rail availability (operational hours of each system, holiday calendar conflicts), counterparty correspondent banking status, settlement-system stress conditions (Fedwire throughput pressure, CHIPS netting cycles, ACH rejection rates, SWIFT message backlogs in correspondent networks), and regulatory regime applicability (FedNow eligibility, CSDR settlement discipline applicability for European operations, jurisdictional payment system compliance). The gate emits PROCEED, HOLD, or ESCALATE plus a recommended FIAT settlement rail consistent with the Cato architecture's multi-rail governance pattern.

The forward-state operational implication: the FIAT-rail governance gate is anticipated as a doctrine extension over the 5-10 year horizon, parallel to Cato's tokenized-rail governance. The architectural commitment in this doctrine is that FIAT settlement-rail selection is governable infrastructure, not an operational default. Custody operations specified in `AUR-CUSTODY-INST-001` and `AUR-CUSTODY-FED-001` will include FIAT-rail selection as a first-class operational option with audit lineage capturing the rail decision per material settlement.

The current state of FIAT rail evolution warrants explicit doctrinal acknowledgment. FedNow, the Federal Reserve's instant payments system launched in 2023, introduces 24/7/365 FIAT settlement capability that parallels the 24/7 operational continuity of tokenized rails. T+1 settlement (US, post-2024 transition) compresses the settlement window for cleared securities. Real-time gross settlement systems globally are extending operational hours and consolidating finality treatment. ISO 20022 migration for SWIFT and Fedwire (in progress through 2025-2027) restructures the message format and settlement-data infrastructure underlying institutional FIAT operations. The doctrine treats each of these as configurable infrastructure beneath the architectural commitment to FIAT-rail governance.

**Forward-state FIAT operations the framework anticipates:**

- 24/7/365 FedNow-class instant FIAT settlement integrated with custody operations
- ISO 20022-native FIAT settlement messaging with full lineage capture
- Real-time cross-border PvP for currency pairs beyond current CLS coverage as wholesale tokenized currency emerges
- Federal Reserve account direct access for entities qualified under future regulatory frameworks
- Wholesale tokenized currency (potentially PORTS-aligned) as a hybrid FIAT-tokenized rail Aureon governs natively
- Central Bank Digital Currency (CBDC) wholesale variants where issued by Federal Reserve, ECB, BoE, BoJ, or other major central banks

The FIAT-rail forward state is real, not speculative. FedNow is operational. ISO 20022 migration is in flight at scale. CBDC pilots are operational at multiple central banks. PORTS-aligned wholesale infrastructure is anticipated within the 5-10 year horizon. The doctrine's architectural commitment is that the framework activates FIAT-rail evolution through configuration rather than rebuild — analogous to how Cato architecture activates tokenized-rail evolution through configuration.

## Atomic Settlement Governance

Atomic settlement — the simultaneous transfer of asset and payment in a single irreversible operation — is operationally available today on multiple tokenized rails (Ethereum L1, Base, Arbitrum, Solana) and is anticipated for wholesale settlement infrastructure (PORTS-aligned wholesale tokenized infrastructure per Duffie's framework, the Federal Reserve's Project Cedar / Project Agorá trajectories, and equivalent international initiatives). Atomic settlement eliminates the settlement-risk window between trade execution and settlement completion, a window that traditional T+1 / T+2 settlement maintains as a structural feature.

Custody under Aureon governance integrates atomic settlement through the Cato governance gate (canonical Section II, Verana L0). Cato evaluates four deterministic checks (OFR systemic stress, ETH gas, SOFR funding shock, plus future PORTS / Fed L1 status) and emits PROCEED, HOLD, or ESCALATE plus a recommended settlement rail. Custody operations requiring atomic settlement query Cato before execution; the gate decision determines whether atomic settlement proceeds on a tokenized rail or whether the operation routes to traditional FICC-style settlement under stress conditions.

The forward-state operational implication: custody operations specified in `AUR-CUSTODY-INST-001` and `AUR-CUSTODY-FED-001` must include atomic settlement as a first-class operational option, not as a special case. Settlement instructions carry a settlement-rail preference; Cato confirms or overrides the preference based on real-time conditions; the executed settlement (whether atomic or traditional) carries full DSOR lineage including the Cato decision. The architecture supports atomic settlement today (Base, Arbitrum, Ethereum L1, Solana per Cato v0.2.2) and supports the PORTS-aligned wholesale infrastructure when it arrives (the `fed_l1` placeholder in Cato chain_state responses, reserved per canonical Section II).

The custody operations affected by atomic settlement are settlement, collateral management (atomic collateral substitution), and corporate actions where the issuer offers tokenized treatment. The framework is rail-agnostic: custody operations under Aureon governance are doctrine-grade regardless of which settlement rail underlies them.

## 24/7 Operational Continuity

Traditional securities markets operate on business-hours schedules with overnight and weekend windows where operations are paused. Tokenized settlement infrastructure operates 24/7 — there is no overnight close on Ethereum L1, no weekend pause on Base, no holiday window on Solana. Wholesale tokenized infrastructure (PORTS-aligned) is anticipated to follow the same 24/7 model because the underlying blockchain infrastructure operates continuously.

Custody under Aureon governance must support 24/7 operations as the forward-state default, not as an exceptional capability. This has architectural implications across the framework:

**Agent availability.** The Tier 1 agent workforce (Settlement Operations Analyst, Trade Support Analyst, Reconciliation Analyst, Regulatory Reporting Analyst, Custody Operations Analyst) must be available 24/7. The agents are software, not human staff, so 24/7 availability is operationally feasible. The architectural commitment is that agent availability is treated as a 24/7 baseline with documented degradation modes per canonical Section IX (Operational Resilience under DORA).

**Operator availability for CAOM-001 authority routing.** Material operations require human authority approval per CAOM-001. In a 24/7 operational environment, operator availability cannot be assumed during traditional business hours only. Operational specifications (Sovereign and Federate) must define on-call rotations, escalation hierarchies for after-hours material operations, and queue-and-batch protocols for non-urgent operations that can wait for next-business-hour authority. The doctrine commits to 24/7 operational availability; the operational specifications detail how human authority routing scales to 24/7.

**Quorum authority ceremony availability.** Quorum authority operations (Section VII) require multiple independent signing authorities. In a 24/7 environment, the signing authority cohort must include sufficient on-call or rotating availability to enable quorum convening within reasonable time bounds for urgent operations. Operational specifications detail the on-call rotation structure.

**Settlement window coordination.** When custody operations span both 24/7 tokenized rails and business-hours traditional rails, the framework must coordinate settlement timing such that operations dependent on both rails complete cleanly. Cato governance gate decisions account for traditional-rail availability when routing recommendations.

**Reporting and reconciliation cadence.** Traditional reporting is daily (end-of-day positions, intraday risk reports, monthly statements). 24/7 operations require continuous reporting — point-in-time position queries available on demand, intraday reconciliation cycles continuous rather than batched, audit lineage complete at every moment regardless of business hours. The DSOR architecture natively supports continuous lineage; operational specifications detail the reporting frequencies and formats.

The 24/7 operational commitment is binding on both Sovereign and Federate operational specifications. Federate Phase 1 deployments may operate on hybrid schedules during transition (overlay above existing custodians with business-hours operations) but the architecture supports 24/7 as the licensee scales.

## Selective FIAT and/or Tokenized Custody

Custody under Aureon governance offers beneficial owners the choice of holding assets in FIAT representations (traditional securities, traditional cash, traditional custodian-held positions) or tokenized representations (tokenized securities on permissioned or public ledgers, tokenized cash via stablecoin or wholesale tokenized currency, tokenized fund interests) or both simultaneously per asset class.

The selectivity is material. Different beneficial owners have different preferences: regulatory regimes vary by jurisdiction and beneficial owner type (some jurisdictions require traditional custody for certain asset classes, some prohibit or restrict tokenized custody, some require both for redundancy); operational requirements vary by beneficial owner sophistication and infrastructure (some beneficial owners are not equipped to hold tokenized assets directly, others prefer tokenized for programmability); risk preferences vary (some beneficial owners view tokenized as higher risk due to rail novelty, others view traditional as higher risk due to settlement-window exposure).

Custody under Aureon governance accommodates the selectivity at the asset-class and beneficial-owner level. A single custody account may hold a single beneficial owner's Treasury exposure as traditional Treasuries (DTC-held), tokenized Treasuries (Ondo OUSG, BlackRock BUIDL, Franklin Templeton FOBXX, or analogous), or both, per the beneficial owner's election. The Aureon framework provides the unified governance, audit lineage, reporting, and reconciliation across both representations.

The forward-state operational implication: custody operations on selective representations require representation-aware logic at every workflow stage. Settlement routes to the appropriate rail per representation. Corporate actions process per the representation's mechanism (issuer-driven for traditional, smart-contract for tokenized). Income flows through the appropriate distribution mechanism. Reporting reconciles both representations under one beneficial-owner account. Operational specifications detail the representation-aware logic for each operation type.

The competitive implication is also material. Beneficial owners increasingly demand the choice. Custodians that cannot offer selective FIAT-and-tokenized custody under unified governance will lose share to those that can. The Aureon framework's native multi-rail architecture (per the canonical doctrine and Cato implementation) positions custody under Aureon as the structurally appropriate offering for the selective-representation forward-state.

## PORTS-Aligned Architecture

The Project on Operational Resilience and Tokenized Settlement (PORTS) framework, articulated in Darrell Duffie's 2025 Brookings paper, defines the architectural target for wholesale tokenized settlement infrastructure that is anticipated to become operational over the 5-10 year horizon. The framework treats tokenized settlement on shared ledgers as the operational architecture for resilient wholesale payments and securities settlement, with central bank reserves and treasury securities as the foundational on-chain assets.

Custody under Aureon governance is positioned for the PORTS-aligned forward-state through the Cato architecture's `fed_l1` placeholder slot, reserved in every Cato chain_state response and ready to activate when wholesale tokenized infrastructure becomes operational. The architectural commitment in this doctrine: custody operations under Aureon governance treat PORTS-aligned wholesale infrastructure as a first-class settlement rail when it arrives, not as a special case requiring architectural rebuild.

The operational specifications (Sovereign and Federate) will detail PORTS-specific custody operations as the wholesale infrastructure becomes operational. Anticipated operations include:

**Tokenized treasury reserves custody.** When the Federal Reserve issues wholesale tokenized reserves (PORTS-aligned), custody of those reserves operates under the same Aureon governance as traditional Federal Reserve account balances or alternative reserve representations.

**Tokenized treasury security custody.** When tokenized Treasuries become operationally available on wholesale infrastructure, custody operates under the same framework as traditional Treasury custody — selectively, per beneficial owner election, with unified governance.

**Atomic DvP on wholesale tokenized rails.** When PORTS-aligned infrastructure supports atomic delivery-versus-payment for wholesale operations, custody operations leverage the atomicity through Cato governance gate routing.

**24/7 wholesale settlement.** PORTS-aligned wholesale infrastructure is anticipated to operate 24/7. Custody under Aureon governance supports the 24/7 operational continuity per Section X.

The doctrine does not depend on PORTS becoming operational reality. Each forward-state element above has commercial value in the current TradFi-dominant world. The doctrine commits to the architectural readiness for the PORTS-aligned future, positioning custody under Aureon governance to activate PORTS-related operations through configuration rather than architectural rebuild — consistent with the broader Aureon architecture's PORTS-aligned positioning.

## Forward-State Risk and Governance Considerations

Three forward-state risk considerations deserve doctrinal treatment:

**Smart-contract risk on tokenized custody.** Tokenized securities and native digital assets are subject to smart-contract risk — bugs, vulnerabilities, or malicious logic in the smart contracts governing the tokens or the protocols the tokens interact with. Custody under Aureon governance addresses smart-contract risk through Axiom 5 (doctrine over code) — Aureon doctrine governs custody decisions regardless of what smart-contract logic permits. Material custody operations involving smart-contract interaction are quorum authority operations (Section VII) with explicit smart-contract risk evaluation in the operation package.

**Cross-rail reconciliation complexity.** Custody operations spanning traditional and tokenized rails require reconciliation across both representations. The reconciliation complexity grows with the number of rails, the number of representation types, and the cross-rail operation frequency. The Reconciliation Analyst (Tier 1) and Custody Operations Analyst (Tier 1) handle the reconciliation work; operational specifications detail the reconciliation cadences, reconciliation data sources, and break-resolution protocols for cross-rail operations.

**Regulatory evolution risk.** The regulatory framework for tokenized custody is evolving and will continue to evolve over the 5-10 year horizon. Custody operations must adapt as regulatory expectations advance — tokenized custody may become subject to specific qualified-custodian requirements, specific reporting standards, specific operational resilience requirements (DORA-equivalent for tokenized infrastructure). The Aureon framework's doctrine version control mechanism (canonical Section VIII propose/approve workflow) is the architectural answer to regulatory evolution: doctrine updates absorb new regulatory requirements without code rebuild.

The forward-state framework is binding on both Sovereign and Federate operational specifications. Each operational specification details its particular forward-state implementation; the architectural commitments in this doctrine constrain both.

---

# XI. BINDING EFFECT

This doctrine binds all subsequent custody-related and asset-services-related work in the Aureon framework. The binding scope is intentionally broad because the asset-class universe in Section III commits the framework to operational coverage that extends beyond custody narrowly defined into the broader Asset Services roadmap.

## Direct Custody-Specification Binding

**`AUR-CUSTODY-FED-001`** (Atreides Federate Phase 1 operational specification, anticipated as the largest single doctrine addition since v1.0 per `AUR-SEGMENT-001`) inherits this doctrine. FED-001 specifies the operational details of Federate custody (governance overlay above existing custodians, no qualified-custodian status held by Aureon in Phase 1) within the architectural constraints established here. FED-001 does not restate this doctrine's commitments; it operationalizes them. FED-001 specifies which asset-class-specialist roles Federate deploys at launch versus deferred to subsequent expansion.

**`AUR-CUSTODY-INST-001`** (Atreides Sovereign operational specification) inherits this doctrine. INST-001 specifies the operational details of Sovereign custody (institutional displacement, tier-1 incumbent platform replacement) within the architectural constraints established here. INST-001 does not restate this doctrine's commitments; it operationalizes them. INST-001 specifies which asset-class-specialist roles Sovereign deploys at launch versus deferred to subsequent expansion.

## Asset Services Roadmap Binding

The Asset Services roadmap (custody → escrow → IPA → fund administration → structured credit re-onboarding → structured credit new issue) inherits this doctrine. Each adjacency is treated as an extension of the asset-services framework rather than as a separate domain. The architectural commitments in this doctrine — asset-class breadth, doctrine-grade governance, complete audit lineage, inherent-safety on declared surfaces, quorum authority for material operations, the four-class failure-mode taxonomy — bind every Asset Services adjacency.

Specifically:

**Escrow operations** under future doctrine (anticipated as `AUR-ESCROW-001` or analogous) inherit the asset-class universe, the workforce framing (Aureon Asset-Services Workforce), the failure-mode taxonomy, and the inherent-safety architecture. Escrow is custody with conditional release governance; the foundation is the same as custody more broadly.

**Indenture Paying Agent (IPA) operations** under future doctrine inherit the same architectural commitments. IPA is asset servicing with debt-instrument-specific operational mechanics; the framework foundation does not change.

**Fund administration** under future doctrine inherits the architectural commitments and adds the fund-specific operational surface (NAV calculation, transfer agency, financial reporting, regulatory filings). The asset-class breadth applies — fund administration covers funds investing across the full asset-class universe, not just traditional securities-only funds.

**Structured credit re-onboarding** under future doctrine inherits the architectural commitments and adds the structured-credit-specific operational surface (collateral pool management, waterfall calculations, trustee functions, investor reporting). The framework's architectural commitments apply to structured credit operations across all underlying asset classes.

**Structured credit new issue** under future doctrine inherits the architectural commitments and adds the new-issue-specific operational surface (structuring support, rating agency interaction, distribution coordination, closing operations).

## Asset-Class-Specific Operational Specification Binding

Future asset-class-specific operational specifications inherit this doctrine. The architectural commitment to every asset class possible (Section III) implies that subsequent doctrine work will produce operational specifications for asset categories that warrant dedicated treatment beyond what FED-001 and INST-001 cover at launch:

- Physical commodity custody operational specifications
- Real estate and real asset custody operational specifications
- Insurance and ILS custody operational specifications
- IP and royalty stream custody operational specifications
- Alternative asset custody operational specifications (art, wine, collectibles)
- Emerging digital asset operational specifications as the category evolves
- Future asset categories not yet operationally significant

Each subsequent specification inherits this doctrine without restating its commitments.

## Code and Implementation Binding

**Custody-related code in Project-Atreides** must trace back to commitments in this doctrine. Code that implements custody operations not specified here, or that contradicts this doctrine's architectural commitments, is doctrine-implementation gap and is not licensable as Aureon-grade custody. The binding extends to all asset-class operational implementations — code handling traditional securities custody is bound, code handling digital asset custody is bound, code handling physical commodity custody is bound, code handling any asset category Section III enumerates is bound.

**Asset Services Code in Project-Atreides** beyond narrow custody — escrow modules, IPA modules, fund administration modules, structured credit modules — is bound when those modules are added to the codebase. The architectural commitments apply across the Asset Services roadmap, not just to the custody slice.

## Strategic and Commercial Binding

**Custody-related capstone deliverables** must align with this doctrine. Academic treatment of custody architecture under Aureon governance must reflect the commitments here, particularly the asset-class-breadth architectural axis, the inherent-safety architecture, the quorum authority specification, and the forward-state framework.

**Commercial materials related to custody and Asset Services** are bound by the framing principle established in `AUR-MARKET-001 v1.0`. Marketing language describing Aureon's custody and asset-services capability respects institutional incumbents (Top 5 custodians named in Section II with their per-segment differentiation) and positions Aureon as architectural foundation rather than as displacement of incumbent capability.

**Anthropic and other model provider engagement** related to custody and asset-services capabilities is bound by the framing principle established in `AUR-MARKET-001 v1.0`. Conversations about Aureon's capability respect institutional incumbents and position Aureon as architectural foundation.

**Regulatory engagement** related to custody and asset-services operations references this doctrine as the framework specification. Discussions with regulators (SEC, OCC, state banking regulators, state insurance regulators, CFTC, jurisdiction-specific regulators for non-US operations) are anchored on the doctrinal commitments here, particularly the inherent-safety architecture and the four-class failure-mode taxonomy.

**Licensing counterparty engagement** for both Sovereign and Federate licensees is bound by this doctrine. Licensee-facing materials describe the framework's commitments per this doctrine; licensee-specific operational deployments are detailed in FED-001 and INST-001 within these architectural constraints.

---

# XII. DOCTRINE LINEAGE AND VERSION ADVANCEMENT

This document advances the Aureon doctrine from v1.5.1 to v1.6 substantively, delivering the custody specification the canonical doctrine has anticipated since v1.5. The canonical document (`AUR-CANONICAL-001`) is updated separately to absorb v1.6 into its version log and to update its open items section to reflect the closure of the custody specification work.

## v1.6 Version Log Entry (to be incorporated into AUR-CANONICAL-001)

| Field | Value |
|---|---|
| Version | 1.6 |
| Authority | Operator (CAOM-001) |
| Tier / Trigger | T1 — Human Authority |
| Reason | Custody specification delivered with asset-class-breadth as the durable architectural axis. `AUR-CUSTODY-001 v1.0` operationalizes the architectural prerequisites established in v1.5 (Axiom 10 inherent-safety, three-class failure-mode taxonomy, quorum authority primitive) within the custody domain. The architectural choice that distinguishes this doctrine: custody under Aureon governance is bounded only by the legal definition of custodiable assets, not by current operational practice and not by the post-trade-shaped mental model of any incumbent platform. Settlement methods are framed as the variable operational layer beneath the durable asset-class architecture, accommodating future evolution (atomic settlement, PORTS-aligned wholesale tokenized infrastructure, currently-unimagined rails) through configuration rather than rebuild. The doctrine specifies the operational definition of custody under Aureon governance, the asset-class universe (traditional securities, fixed income, derivatives, FX, funds, commodities both physical and financial, real estate and real assets, insurance and reinsurance, intellectual property, trade finance, tokenized representations of all above, native digital assets, alternative and specialty assets, and emerging future categories), the custody object inventory mapped onto operational workflows, the comprehensive enumeration of transaction types and settlement methods across the asset-class universe, the custody-specific roles added to the eFICC workforce (Custody Operations Analyst at Tier 1, Collateral Operations Specialist and Digital Asset Custody Specialist at Tier 2), the operational quorum authority specification, the four-class custody-specific UR-R / UR-F failure-mode taxonomy refinement, the inherent-safety architecture per Axiom 10, and the forward-state framework covering atomic settlement, 24/7 operational continuity, selective FIAT/tokenized custody, and PORTS-aligned architecture. Anchored in modern Top 5 institutional custody practice (BNY Mellon for global custody breadth and tri-party, State Street for institutional asset managers and ETFs, JPMorgan for systematic strategy funds and prime brokerage integration, Citi for cross-border emerging markets and FX-bundled custody, BNP Paribas Securities Services for European institutional and post-trade integration) with explicit recognition that no single Top 5 incumbent serves every asset-class segment — the framework's competitive position is the asset-class breadth no individual custodian provides. Foundation for the two anticipated product-specific operational specifications (`AUR-CUSTODY-FED-001` for Atreides Federate, `AUR-CUSTODY-INST-001` for Atreides Sovereign) and for the Asset Services roadmap (custody → escrow → IPA → fund administration → structured credit re-onboarding → structured credit new issue) per the strategic positioning developed in supporting analysis. |

## Predecessor and Successor Documents

The predecessor advancement was `AUR-MARKET-001 v1.0` (Institutional AI Deployment Reality Doctrine, advanced v1.9 → v2.0). This document advances v1.5.1 → v1.6 substantively within the canonical line, alongside the v2.0 brand-architecture line established by the Aureon - Asset Services rename. The two version lines run in parallel: the canonical doctrine lineage tracks substantive doctrinal additions (v1.4 → v1.5 → v1.5.1 → v1.6 with this document); the parallel Atreides product-architecture lineage tracks brand and segmentation evolution (`AUR-SEGMENT-001 v1.0` advanced the segmentation lineage; `AUR-MARKET-001 v1.0` continued it; the rename cascade is anticipated work).

Anticipated subsequent doctrine work, in priority order:

**`AUR-CUSTODY-FED-001`** (Atreides Federate Phase 1 operational specification). The largest single doctrine addition since v1.0 per `AUR-SEGMENT-001`. Operationalizes Federate custody under this doctrine's foundation. Anticipated as the next major doctrine work after this document.

**`AUR-CUSTODY-INST-001`** (Atreides Sovereign operational specification). Operationalizes Sovereign custody under this doctrine's foundation. Less novel architecturally than FED-001 because Sovereign is comprehensive deployment of the existing Aureon stack.

**Aureon - Asset Services rename cascade** through `AUR-SEGMENT-001`, `AUR-CUSTODY-OBJ-001`, and the broader doctrine corpus. Anticipated work alongside or following the FED-001 / INST-001 specifications.

**Updated `AUR-CANONICAL-001 v1.6`**. The canonical document is updated to absorb this doctrine into its version log and update its open items section. This is operational doctrine-corpus work, not new substantive doctrine.

---

# XIII. OPEN ITEMS

The following items are open at the time of this document's adoption and require closure through subsequent doctrine work or operational decisions.

**Quorum authority operational thresholds.** The N-of-M structure is specified at default 3-of-5 with adjustment ranges named, but the specific magnitude thresholds that trigger different N-of-M configurations are deferred to the product-specific operational specifications (FED-001 and INST-001). Each product's deployment context determines appropriate thresholds.

**Quorum authority signing infrastructure selection.** The signature ceremony protocol is specified architecturally, but the specific cryptographic infrastructure (multi-signature wallet implementations, MPC platforms, threshold signature schemes, traditional ceremony platforms) is deferred to operational specifications and licensee deployment configurations.

**24/7 operator availability protocols.** The 24/7 operational continuity commitment is binding, but the specific on-call rotation structures, escalation hierarchies, and queue-and-batch protocols for after-hours operations are deferred to operational specifications.

**Cross-rail reconciliation cadences.** The cross-rail reconciliation requirement is established, but the specific reconciliation frequencies, data sources, and break-resolution protocols are deferred to operational specifications.

**Tokenized custody regulatory positioning.** The forward-state framework establishes architectural commitments for tokenized custody, but the regulatory positioning (which jurisdictions, which qualified-custodian frameworks, which reporting standards) is deferred to operational specifications and ongoing regulatory engagement work.

**Custody-specific Tier 3 roles.** This doctrine adds Tier 1 and Tier 2 custody-specific roles but does not add Tier 3 roles. Subsequent doctrine work may add adaptive intelligence custody roles (Custody Risk Manager, custody-specific model risk, custody data governance) if operational experience identifies the need.

**Insurance and indemnification frameworks for UR-R failures.** The four-class failure-mode taxonomy distinguishes UR-R (recoverable through external mechanisms) from UR-F (final). Operational specifications must detail the specific insurance and indemnification arrangements that bound UR-R economic exposure for licensees.

**PORTS activation protocols.** The architectural readiness for PORTS-aligned wholesale tokenized infrastructure is established, but the specific activation protocols (governance approvals, operational rollout, Cato configuration updates, beneficial owner notification) are deferred to the time when PORTS infrastructure becomes operational.

**Anthropic and model provider engagement on custody capabilities.** Custody operations may interact with Claude or other model infrastructure as part of the agent workforce execution. Specific arrangements with Anthropic on custody-grade deployment guarantees, audit access to model behavior, and operational continuity commitments are deferred to commercial conversations bounded by the framing principle in `AUR-MARKET-001`.

---

# CLOSING

This is v1.0 of `AUR-CUSTODY-001`, the Aureon Custody Operational Doctrine. It delivers the custody specification the Aureon canonical doctrine has anticipated since v1.5, advancing the doctrine substantively from v1.5.1 to v1.6.

The doctrine specifies what custody is under Aureon governance, anchored in modern Top 5 institutional custody practice and built on the architectural prerequisites established in canonical v1.5. It maps the custody object inventory onto operational workflows, adds custody-specific roles to the eFICC workforce, operationalizes quorum authority for custody operations of material magnitude, refines the failure-mode taxonomy with the four-class custody-specific distinction, declares custody surfaces inherent-safety per Axiom 10, and establishes the forward-state framework for the 5-10 year horizon covering atomic settlement, 24/7 operational continuity, selective FIAT/tokenized custody, and PORTS-aligned architecture.

The doctrine is the shared foundation for the two anticipated product-specific operational specifications: `AUR-CUSTODY-FED-001` (Atreides Federate Phase 1 governance overlay) and `AUR-CUSTODY-INST-001` (Atreides Sovereign institutional displacement). Both inherit this doctrine's commitments and operationalize them within their respective product contexts.

The doctrine binds all subsequent custody-related work in the Aureon framework: subordinate doctrine, code implementations, capstone deliverables, commercial materials, and model provider engagement. It exists to ensure that custody under Aureon governance is doctrinally specified before it is operationally deployed, consistent with canonical Axiom 1 (doctrine before execution).

The next anticipated doctrine work is `AUR-CUSTODY-FED-001`. The next anticipated code work is the implementation of custody capability in Project-Atreides under the architectural constraints this doctrine establishes. Both depend on this doctrine being in place; both are now possible because this doctrine exists.

*— End of AUR-CUSTODY-001 v1.0 —*

*Aureon · Columbia University M.S. Technology Management*
*AUR-CUSTODY-001 · v1.0 · Aureon Doctrine v1.6*
