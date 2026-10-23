"""DATA-1 source-only governed public-market-data store.

The package is excluded from the Atreides wheel and refuses production-profile
imports.  It stores data outside repositories and has no live-market client.
"""

from __future__ import annotations

import os

if os.getenv("ATREIDES_PROFILE", "research").lower() == "production":
    raise ImportError("the DATA-1 market-data store is unavailable in the production profile")

__all__: list[str] = []
