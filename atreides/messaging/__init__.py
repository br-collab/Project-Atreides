"""ISO 20022 messaging — canonical model, profiles, emit path, readback.

Per AUR-CUSTODY-CASH-001 v0.2 Section VIII. The domain speaks canonical,
the wire speaks ISO 20022, and the DepositoryProfile is the only thing that
knows the difference.

The emit path prepares; a human submits; ``readback`` brings the venue's
answer back in. Nothing here submits, and nothing here resubmits.
"""

from atreides.messaging.canonical import (
    CashLegInstruction,
    FinancialInstitution,
    SettlementMethod,
    settlement_method_for_rail,
)
from atreides.messaging.emit import (
    InstructionArtifact,
    emit_business_application_header,
    emit_fi_credit_transfer,
    emit_instruction_artifact,
)
from atreides.messaging.profile import BASE_ISO_20022, DepositoryProfile
from atreides.messaging.readback import (
    ReadbackBreak,
    ReadbackBreakCode,
    ReadbackMatch,
    ReadbackParseError,
    SettlementStatus,
    StatusReport,
    absent_readback,
    ingest_readback,
    parse_status_report,
)

__all__ = [
    "BASE_ISO_20022",
    "CashLegInstruction",
    "DepositoryProfile",
    "FinancialInstitution",
    "InstructionArtifact",
    "ReadbackBreak",
    "ReadbackBreakCode",
    "ReadbackMatch",
    "ReadbackParseError",
    "SettlementMethod",
    "SettlementStatus",
    "StatusReport",
    "absent_readback",
    "emit_business_application_header",
    "emit_fi_credit_transfer",
    "emit_instruction_artifact",
    "ingest_readback",
    "parse_status_report",
    "settlement_method_for_rail",
]
