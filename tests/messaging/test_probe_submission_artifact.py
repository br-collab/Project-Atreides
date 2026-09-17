"""ATR-I-03 probe: a submission artifact must be unconstructible at runtime.

``InstructionArtifact.is_submission`` is typed ``Literal[False]``, but the class
is a plain dataclass, so the type is enforced only by a static checker. The
Atreides inventory probe (15 Sep 2026, commit 31b62f0) constructed one with
``is_submission=True`` and it was accepted. The no-submission boundary is
documentary in this one contract; ``InstructionPackage`` enforces it at runtime.

Marked strict xfail: CI stays green while the defect stands, and the run fails
the day the Wave 2 fix (work package T1) lands without the marker being removed.
"""

from __future__ import annotations

import pytest

from atreides.messaging.emit import InstructionArtifact


@pytest.mark.xfail(strict=True, reason="ATR-I-03 — fixed in Wave 2")
def test_instruction_artifact_with_is_submission_true_raises() -> None:
    with pytest.raises((TypeError, ValueError)):
        InstructionArtifact(
            header_xml=b"<AppHdr/>",
            document_xml=b"<Document/>",
            message_definition="pacs.009.001.13",
            profile_name="base-iso20022",
            profile_verified=True,
            dsor_lineage_uri=None,
            is_submission=True,  # type: ignore[arg-type]
        )
