"""SIM-1 source-only synthetic market and settlement-day simulator.

This package is deliberately excluded from the Atreides wheel.  Production refuses
even a source-tree import; generated facts never lose their FACT_SYNTHETIC label.
"""

from __future__ import annotations

import os

if os.getenv("ATREIDES_PROFILE", "research").lower() == "production":
    raise ImportError("the SIM-1 simulator is unavailable in the production profile")

from simulator.runner import run_simulation

__all__ = ["run_simulation"]
