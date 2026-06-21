"""Tier 1 agent implementations — Thifur-R (deterministic, zero-variance).

Per AUR-CANONICAL-001 v1.6 Section II (Thifur-R — R-class) and
AUR-CUSTODY-001 v1.0 Section VI (Custody-Specific Roles).

Tier 1 agents are fully deterministic: zero variance, no path selection.
Every routing decision is pre-defined by doctrine. No instruction is issued
without a confirmed DSOR pre-trade record reference. All outputs are
frozen, immutable, and DSOR-persisted.

The first agent in this tier is the Settlement Operations Analyst
(:mod:`aureon.agents.tier1.settlement_operations_analyst`), the R-class
execution agent for FICC GSD, FICC GCF Repo, and Fedwire settlement paths.
"""

from __future__ import annotations
