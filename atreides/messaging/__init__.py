"""ISO 20022 messaging — canonical settlement model, profiles, emit path.

Per AUR-CUSTODY-CASH-001 v0.2 Section VIII. The domain speaks canonical,
the wire speaks ISO 20022, and the DepositoryProfile is the only thing that
knows the difference.
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

__all__ = [
    "BASE_ISO_20022",
    "CashLegInstruction",
    "DepositoryProfile",
    "FinancialInstitution",
    "InstructionArtifact",
    "SettlementMethod",
    "emit_business_application_header",
    "emit_fi_credit_transfer",
    "emit_instruction_artifact",
    "settlement_method_for_rail",
]
