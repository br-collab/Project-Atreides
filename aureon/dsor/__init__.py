"""DSOR — Decision System of Record assembly and persistence.

Per AUR-CANONICAL-001 v1.6 Layer 2 (Kaladan — Lifecycle Orchestration)
and Axiom 4 (One Lineage Record). Provides:

- :data:`AureonOutput` — unified discriminated union of all agent output
  types storable in the DSOR. Discriminated on the ``kind`` literal field.
- :class:`DSORRecord` — immutable, DTG-stamped wrapper around any
  :data:`AureonOutput`.
- :class:`DSORStore` — append-only SQLite backend. No UPDATE or DELETE
  is ever issued. Corrections write new records referencing the original.
- :class:`DSORAppendOnlyError` — raised when an append would overwrite
  an existing record (Axiom 4 enforcement).
- :class:`DSORRecordNotFoundError` — raised when ``record_id`` is absent.
"""

from aureon.dsor.record import AureonOutput, DSORRecord, RecordKind
from aureon.dsor.store import DSORAppendOnlyError, DSORRecordNotFoundError, DSORStore

__all__ = [
    "AureonOutput",
    "DSORAppendOnlyError",
    "DSORRecord",
    "DSORRecordNotFoundError",
    "DSORStore",
    "RecordKind",
]
