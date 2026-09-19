"""Project Atreides — post-trade settlement, clearing and investigation.

Source of truth: `doctrine/AUR-CANONICAL-001-v1_6.md` and
`doctrine/AUR-CUSTODY-001-v1_0.md`.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

try:
    __version__ = _dist_version("atreides")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"

#: The doctrine version lives in `atreides.contracts.dsor_stub` as
#: CURRENT_DOCTRINE_VERSION, which is the one every record is stamped with. A
#: second copy used to sit here, unused, at a value that could drift from it.
#: Import it from there.

__all__ = ["__version__"]
