"""DSORStore — append-only SQLite backend for DSOR records.

Enforces AUR-CANONICAL-001 v1.6 Axiom 4 (immutable lineage) at two layers:

1. **Schema layer**: a partial unique index on ``(operation_id) WHERE
   correction_of IS NULL`` ensures SQLite itself rejects a second
   "original" record for the same operation. Only one non-correction
   record may exist per ``operation_id``; corrections (``correction_of``
   is not NULL) are exempt from the constraint so the correction chain
   can accumulate.

2. **Application layer**: :class:`DSORStore` exposes only :meth:`append`
   and :meth:`replay`. There is no ``update()``, no ``delete()``, and no
   raw SQL surface. A caller cannot overwrite a record without explicitly
   raising :class:`DSORAppendOnlyError`.

Thread safety: ``check_same_thread=False`` is set; the caller is
responsible for external synchronization under concurrent writes.

The ``_output_adapter`` handles :data:`~aureon.dsor.record.AureonOutput` —
the unified discriminated union of all agent output types. The ``kind``
field on each output type serves as the discriminator.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import TypeAdapter

from aureon.dsor.record import AureonOutput, DSORRecord

# ---------------------------------------------------------------------------
# Schema DDL — created once per connection; idempotent.
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS dsor_records (
    record_id     TEXT PRIMARY KEY,
    operation_id  TEXT NOT NULL,
    dtg           TEXT NOT NULL,
    kind          TEXT NOT NULL,
    payload       TEXT NOT NULL,
    correction_of TEXT
)
"""

# Partial index: only one non-correction record per operation_id.
# SQLite supports partial indexes since 3.8.9 (macOS ships ≥ 3.39).
_CREATE_PARTIAL_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_dsor_op_id_original
ON dsor_records (operation_id)
WHERE correction_of IS NULL
"""

_INSERT = """
INSERT INTO dsor_records (record_id, operation_id, dtg, kind, payload, correction_of)
VALUES (?, ?, ?, ?, ?, ?)
"""

_SELECT_BY_RECORD_ID = """
SELECT kind, payload
FROM dsor_records
WHERE record_id = ?
"""

# ---------------------------------------------------------------------------
# Pydantic TypeAdapter for discriminated-union deserialization.
# ---------------------------------------------------------------------------

_output_adapter: TypeAdapter[AureonOutput] = TypeAdapter(AureonOutput)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DSORAppendOnlyError(Exception):
    """Raised when an attempt would overwrite an existing DSOR record.

    Per AUR-CANONICAL-001 v1.6 Axiom 4 (immutable lineage): the lineage
    record is stamped at execution and never modified. A second record for
    the same ``operation_id`` without ``correction_of`` violates this
    invariant.

    To correct a record, pass ``correction_of=<original_record_id>`` to
    :meth:`DSORStore.append`; the original is preserved and a new record
    is appended referencing it.
    """


class DSORRecordNotFoundError(KeyError):
    """Raised by :meth:`DSORStore.replay` when ``record_id`` is absent."""


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class DSORStore:
    """Append-only SQLite-backed DSOR record store.

    Usage::

        with DSORStore(":memory:") as store:
            record = store.append(output, dtg=now)
            replayed = store.replay(record.record_id)
            assert replayed.model_dump_json() == output.model_dump_json()

    On-disk usage (survives process restart)::

        db_path = Path("/var/lib/aureon/dsor.db")
        with DSORStore(db_path) as store:
            record = store.append(output, dtg=now)

        # After restart:
        with DSORStore(db_path) as store:
            replayed = store.replay(record.record_id)
    """

    def __init__(self, db_path: Path | str) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TABLE)
        self._conn.execute(_CREATE_PARTIAL_INDEX)
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def __enter__(self) -> DSORStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def append(
        self,
        output: AureonOutput,
        *,
        dtg: datetime | None = None,
        correction_of: UUID | None = None,
    ) -> DSORRecord:
        """Append a new DSOR record for ``output``.

        Args:
            output: The :data:`AureonOutput` to record.
            dtg: UTC DTG stamp. Defaults to ``datetime.now(UTC)``.
            correction_of: When set, this record corrects the existing
                record with the given ``record_id``. The original is
                preserved unchanged. When ``None``, ``output.operation_id``
                must not already have a non-correction record in the store.

        Returns:
            The assembled :class:`DSORRecord` (with a fresh ``record_id``).

        Raises:
            DSORAppendOnlyError: If ``correction_of`` is ``None`` and a
                non-correction record for ``output.operation_id`` already
                exists, or if a ``record_id`` collision occurs (vanishingly
                unlikely with uuid4 but enforced by the PRIMARY KEY).
        """
        if dtg is None:
            dtg = datetime.now(tz=UTC)

        record = DSORRecord.assemble(output, dtg=dtg, correction_of=correction_of)
        payload = output.model_dump_json()
        correction_str = str(correction_of) if correction_of is not None else None

        try:
            self._conn.execute(
                _INSERT,
                (
                    str(record.record_id),
                    str(output.operation_id),
                    dtg.isoformat(),
                    record.kind,
                    payload,
                    correction_str,
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            raise DSORAppendOnlyError(
                f"DSOR append-only violation: a non-correction record for "
                f"operation_id={output.operation_id!s} already exists. "
                f"To correct it, pass correction_of=<original_record_id>. "
                f"Per AUR-CANONICAL-001 v1.6 Axiom 4 (immutable lineage)."
            ) from exc

        return record

    def replay(self, record_id: UUID) -> AureonOutput:
        """Fetch and deserialize a DSOR record by ``record_id``.

        Two calls with the same ``record_id`` return byte-identical results
        (determinism invariant): the stored JSON blob is fixed at append
        time and never modified.

        Args:
            record_id: The ``record_id`` of the record to fetch.

        Returns:
            The :data:`AureonOutput` that was appended.

        Raises:
            DSORRecordNotFoundError: If ``record_id`` is not in the store.
        """
        row = self._conn.execute(_SELECT_BY_RECORD_ID, (str(record_id),)).fetchone()
        if row is None:
            raise DSORRecordNotFoundError(record_id)
        _kind, payload = row
        return _output_adapter.validate_json(payload)


__all__ = [
    "DSORAppendOnlyError",
    "DSORRecordNotFoundError",
    "DSORStore",
]
