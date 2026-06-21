"""Tier 2 agent implementations — Thifur-J (bounded autonomy).

Per AUR-CANONICAL-001 v1.6 Section II (Thifur-J — JTAC) and
AUR-CUSTODY-001 v1.0 Section VI (Custody-Specific Roles in the Aureon
Asset-Services Workforce).

Tier 2 agents select among pre-approved paths defined in Kaladan-managed
routing tables; they never generate new paths. Code does not override
doctrine — when external system messages or instructions conflict with
doctrine, the agent holds and escalates to operator authority via
Thifur-C2.

The first agent module in this tier is the FIAT Operations Specialist
(:mod:`aureon.agents.tier2.fiat_operations_specialist`), the 1:1 parity
counterpart to the Digital Asset Custody Specialist per AUR-CUSTODY-001
v1.0 Section VI. Subsequent builds add the Digital Asset Custody
Specialist and the Collateral Operations Specialist.
"""

from __future__ import annotations
