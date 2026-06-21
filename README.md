# Aureon — Project-Atreides

The clean licensable framework codebase for the Aureon doctrine-governed
institutional asset-services platform. The implementation is the doctrine
corpus rendered as code.

## Source of truth — two doctrine documents

The authoritative doctrine for this build lives in `doctrine/`:

- `doctrine/AUR-CANONICAL-001-v1_6.md` — Aureon Consolidated Canonical
  Doctrine v1.6 (framework architecture, governance axioms, Aureon
  Asset-Services Workforce, CAOM-001).
- `doctrine/AUR-CUSTODY-001-v1_0.md` — Aureon Custody Operational Doctrine
  v1.0 (custody-specific operational doctrine, the substantive content of
  v1.6).

Every module in the codebase traces back to commitments in these two
documents. Code that does not is suspect.

## Status — multi-tier framework (contracts + agents + DSOR persistence)

The build delivers the typed contracts substrate, two operational agents, and
append-only decision persistence:

- `aureon/contracts/` — Pydantic v2 typed substrate for custody operations
  (asset class, custody object, settlement, failure mode, inherent safety,
  quorum, DSOR lineage).
- `aureon/agents/tier2/` — FIAT Operations Specialist (path selection,
  eligibility, J-class guardrails, material-magnitude quorum routing).
- `aureon/agents/tier1/` — Settlement Operations Analyst (deterministic R-class
  FICC / U.S. Treasury clearing settlement, DSOR write-through).
- `aureon/dsor/` — append-only DSOR persistence (SQLite WAL, DTG-stamped record
  assembly, deterministic replay).

Not yet built: quorum ceremony state machine, rail integration, additional
Tier-1/Tier-2 agents, API/entry point. The DSOR layer is append-only by
construction; cryptographic tamper-evidence (hash chaining) is roadmap.

The contracts cover:

| Module | Doctrine reference |
| --- | --- |
| `aureon/contracts/asset_class.py` | AUR-CUSTODY-001 v1.0 Section III |
| `aureon/contracts/custody_object.py` | AUR-CUSTODY-001 v1.0 Section IV |
| `aureon/contracts/operations/` | AUR-CUSTODY-001 v1.0 Section V |
| `aureon/contracts/settlement.py` | AUR-CUSTODY-001 v1.0 Section V |
| `aureon/contracts/failure_mode.py` | AUR-CUSTODY-001 v1.0 Section VIII + AUR-CANONICAL-001 Section VI |
| `aureon/contracts/inherent_safety.py` | AUR-CUSTODY-001 v1.0 Section IX + AUR-CANONICAL-001 Axiom 10 |
| `aureon/contracts/quorum.py` | AUR-CUSTODY-001 v1.0 Section VII |
| `aureon/contracts/dsor_stub.py` | AUR-CANONICAL-001 v1.6 Layer 2 (Kaladan) |
| `aureon/agents/tier2/` | AUR-CUSTODY-001 v1.0 Section VI |
| `aureon/agents/tier1/` | AUR-CANONICAL-001 v1.6 Section IV |
| `aureon/dsor/` | AUR-CANONICAL-001 v1.6 Layer 2 (Kaladan) |

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Testing

```bash
pytest
```

## Linting and type checking

```bash
ruff check aureon tests
mypy aureon
```

## Architecture conventions

- **Pydantic v2** for all contract types. Runtime validation is required,
  not optional.
- **Strict typing.** mypy in strict mode. No `Any` without justification.
- **Doctrine traceability.** Every non-trivial validator carries a comment
  naming the doctrine section that justifies it.
- **No silent failures.** Every error is raised. Doctrine Axiom 10
  (inherent-safety) means the framework fails loudly toward safe states,
  never quietly toward operational continuation.
- **Tests live alongside modules.** Each contract module has a
  corresponding test module under `tests/contracts/`. Every validator
  has a positive and a negative test.

## License

MIT License — Copyright (c) 2026 Guillermo Ravelo. See [LICENSE](LICENSE) for full terms.
