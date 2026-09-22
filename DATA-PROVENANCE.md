# Data provenance

Every input this repository holds, distributes, or reads at runtime, with its
source and its licence. The purpose is that the claim in the README can be
checked rather than believed.

Audited 11 September 2026 against the working tree.

## 1. Distributed in this repository

| What | Where | Source | Licence | Notes |
|---|---|---|---|---|
| ISO 20022 message schemas | `tests/fixtures/iso20022/*.xsd` | ISO 20022 Registration Authority, published message definitions | **Redistribution terms not verified — see `tests/fixtures/iso20022/NOTICE.md`.** Published by the Registration Authority for implementation use, which is not a redistribution grant | `pacs.008.001.14`, `pacs.009.001.13`, `pacs.002.001.16`, `head.001.001.04`. Held so emitted messages are validated against the real schema rather than a paraphrase of it. |
| Three `pacs.002` status reports | `tests/fixtures/third_party/issettled/` | `github.com/issettled/iso20022-issettled`, retrieved 14 August 2026 | **Apache License 2.0**, full text and `NOTICE.md` alongside the files | Unmodified. Retained verbatim including the proprietary envelope and signature block, because the point of holding them is that they are not what this framework would have written. Apache 2.0 permits redistribution, so they travel lawfully under this repository's own grant. |
| Doctrine documents | `doctrine/*.md` | Authored by the repository owner | MIT, with the rest of the repository | `AUR-CANONICAL-001`, `AUR-CUSTODY-001`, `AUR-COCKPIT-001` and the path sets. |
| Everything else | source, tests, docs | Authored by the repository owner | MIT | |

There is no other third-party material in this repository. No market data
file, no price series, no security master, no holder record, no identifier
list.

## 2. Read at runtime

| Input | How it arrives | Source class |
|---|---|---|
| `ofr_stlfsi4` | Supplied by the caller as a value | Office of Financial Research Financial Stress Index. Public, United States Treasury, no redistribution restriction. This framework does not fetch it. |
| Rail states, cutoffs, value caps | Supplied by the caller | Caller's own operational knowledge |
| Counterparty standing and provenance | Supplied by the caller | Caller's own credit process. Consumed, never derived |
| Materiality, eligibility, determination outcome | Supplied by the caller | Caller's own policy functions |
| Settlement perimeter, freshness policy | Supplied by the caller | Caller's own declaration |

The framework reads no external source. `funding_state.py` states the rule
directly: input arrives as a value, and the caller's refresh loop owns data
fetching. That is a design choice about replayability, and it has the side
effect that no data licence can attach to this code through use.

## 3. Identifiers

**No CUSIPs, ISINs or other licensed identifiers appear anywhere in this
repository.** Fields whose names reference an identifier scheme carry
synthetic values (`net_cusip="GC-POOL-BNY"` is a label, not a CUSIP).

Where an identifier scheme is needed in future work the intended choice is
**OpenFIGI**, which is free, open, and carries no anti-stripping clause.

## 4. Named institutions

Two different things are deliberately treated differently.

**Market infrastructure is named.** The Depository Trust Company, the Fixed
Income Clearing Corporation, Fedwire, CHIPS, FedNow, the National Settlement
Service, CLS, and BNY Mellon in its published role as a General Collateral
Finance Repo pool custodian. Naming these models public market structure,
which is the subject matter. Removing them would make the framework less
accurate, not more careful.

**Commercial banks acting as parties are not named.** Correspondents,
instructing banks, beneficiary banks and counterparties in the default
approved-path registry, the message fixtures and the walkthrough carry
placeholder Business Identifier Codes (`AAAAUS33`, `BBBBDEFF`, `CCCCGB2L`,
`DDDDUS33`, `EEEEUS33`, `FFFFUS33`) rather than real ones.

This changed on 11 September 2026. The default registry previously shipped
named real institutions as approved correspondents with their live codes. A
default registry is read as a recommendation, and this framework has no
basis on which to recommend any institution as a correspondent. The shape of
the path is the doctrine; the identity of the bank was never part of it.

## 5. What is out of scope and stays out

No data licensed for academic or non-commercial use is used in, derived
into, or distributed with this repository. That includes anything reachable
through a university subscription. The MIT grant on this repository permits
downstream users to redistribute and to sell, and material held under an
academic licence cannot travel under that grant. Where such data is used in
academic work it stays in the academic work.

## 6. How to re-run this audit

```sh
find . -path ./.git -prune -o -type f \( -name "*.csv" -o -name "*.json" \
  -o -name "*.parquet" -o -name "*.xlsx" -o -name "*.pdf" \) -print
grep -rnoE '\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b' --include=*.py --include=*.md .
grep -rhoE '"[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?"' --include=*.py . | sort -u
```

The first finds data files, the second identifier-shaped tokens, the third
every Business Identifier Code in the source. All three should return only
what this document accounts for.
