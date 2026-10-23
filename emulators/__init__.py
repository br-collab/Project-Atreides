"""Synthetic inbound sources; deliberately excluded from the Atreides wheel."""

import os

if os.getenv("ATREIDES_PROFILE", "research").lower() == "production":
    raise ImportError("emulators are unavailable in the production profile")
