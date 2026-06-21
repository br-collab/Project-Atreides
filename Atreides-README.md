# Aureon - Atreides

Atreides is the custody and asset-services build of Aureon, the doctrine-governed
institutional operating framework. This repository renders the Aureon custody
doctrine as code: the typed substrate against which all custody operations are
implemented. The implementation is the doctrine corpus rendered as code.

Aureon's pre-trade governance and Decision System of Record work lives in
separate builds; Atreides is the custody face of the same doctrine spine.

## Source of truth - two doctrine documents

The authoritative doctrine for this build lives in `doctrine/`:

- `doctrine/AUR-CANONICAL-001-v1_6.md` - Aureon Consolidated Canonical
  Doctrine v1.6 (framework architecture, governance axioms, Aureon
  Asset-Services Workforce, CAOM-001).
- `doctrine/AUR-CUSTODY-001-v1_0.md` - Aureon Custody Operational Doctrine
  v1.0 (custody-specific operational doctrine, the substantive content of
  v1.6).

Every module in the codebase traces back to commitments in these two
documents. Code that does not is suspect.

## Status - Phase 1 (in progress): contracts layer

The current build delivers the **typed substrate** (Pydantic v2 contracts)
that all subsequent custody code will implement against. No agents, no
ceremonies, no rails, no DSOR persistence, no API endpoints - just the
machine-checkable encoding of what custody operations *are* under Aureon
governance.

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

Subsequent phases (workforce agents, quorum ceremony, DSOR persistence,
rail integration, product-specific specs for Federate and Sovereign) will
build against this substrate without restating its commitments.

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

MIT License. Released as part of academic work at Columbia University
(M.S. Technology Management). See `LICENSE` at the repository root.
