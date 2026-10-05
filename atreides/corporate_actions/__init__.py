"""Corporate action events: lifecycle, entitlement and their DSOR records (ORDER SC-1).

EXPERIMENTAL (charter section 18.6). Nothing here is production evidence, and
nothing here transmits. Atreides prepares; an entitled member submits.

- :mod:`~atreides.corporate_actions.events`: the event as announced, its dates
  and terms, and who reported it.
- :mod:`~atreides.corporate_actions.lifecycle`: which milestones may follow
  which, the journal of requests, and rebuilding a lifecycle from it.
- :mod:`~atreides.corporate_actions.record`: the DSOR-admissible record of each
  lifecycle request, election submission and default assignment.
- :mod:`~atreides.corporate_actions.election`: the election workflow for elective
  events: the firm's deadline, late and duplicate submissions, protect and its
  cover, and the announced default.
- :mod:`~atreides.corporate_actions.movement`: what a depository says it will move or
  has moved for one account, in its own balance vocabulary.
- :mod:`~atreides.corporate_actions.iso20022`: a synthetic adapter between these models
  and DTC's ISO 20022 profiles (seev.031, 033, 035, 036) at SR2025 and SR2026, with
  structural validation only; :mod:`~atreides.corporate_actions.dtc_sources` pins the
  DTC material it was built from.
- :mod:`~atreides.corporate_actions.reconciliation`: entitlements reconciled against
  movement confirmations, in the depository's break vocabulary where it has one.
- :mod:`~atreides.corporate_actions.entitlement`: entitlement arithmetic for cash
  dividends, stock dividends and forward splits, exact and unrounded, refusing by
  name every treatment the depository does not state.

This package reconciles and does not invent. Where a depository states a
condition but not its treatment, the treatment is refused by name rather than
supplied (see :func:`atreides.rails.cns.absent_entitlement_treatment`).
"""

from atreides.corporate_actions.dtc_sources import (
    DTC_PACKAGES,
    DTC_XSDS,
    DtcPackage,
    DtcXsd,
    MessageFamily,
    Release,
)
from atreides.corporate_actions.election import (
    AccountDefault,
    DefaultAssignment,
    DefaultRefusal,
    ElectionBook,
    ElectionEntry,
    ElectionInstruction,
    ElectionPolicy,
    ElectionRefusal,
    ProtectCover,
    Submission,
    assign_defaults,
    firm_deadline,
    rebuild_elections,
)
from atreides.corporate_actions.entitlement import (
    COMPUTED_EVENT_TYPES,
    EntitlementResult,
    HolderEntitlement,
    HolderPosition,
    UnavailableTreatment,
    compute_entitlements,
)
from atreides.corporate_actions.events import (
    EVENT_FACT_PROVENANCE,
    CorporateActionEvent,
    ElectionOption,
    EventDates,
    EventTerms,
    EventType,
    OptionType,
    Participation,
    SourceIdentity,
)
from atreides.corporate_actions.iso20022 import (
    PROFILES,
    AdapterRefusalError,
    AdapterRefusalReason,
    EncodedMessage,
    MessageProfile,
    decode_announcement,
    decode_instruction,
    decode_movement,
    encode_announcement,
    encode_instruction,
    encode_movement,
)
from atreides.corporate_actions.lifecycle import (
    JournalMismatchError,
    Lifecycle,
    LifecycleState,
    LifecycleStatus,
    Milestone,
    RefusalReason,
    TransitionEntry,
    TransitionRequest,
    rebuild,
)
from atreides.corporate_actions.movement import (
    CashMovement,
    MovementBalances,
    MovementReport,
    SecuritiesMovement,
)
from atreides.corporate_actions.reconciliation import (
    AccountReconciliation,
    CorporateActionBreakCode,
    CorporateActionReconciliation,
    reconcile,
)
from atreides.corporate_actions.record import (
    CorporateActionEventRecord,
    DefaultAssignmentBody,
    ElectionBody,
    LifecycleTransitionBody,
    ReconciliationBody,
    RecordBody,
    rebuild_elections_from_records,
    rebuild_from_records,
    record_defaults,
    record_reconciliation,
    record_request,
    record_submission,
    verify_reconciliation,
)

__all__ = [
    "COMPUTED_EVENT_TYPES",
    "DTC_PACKAGES",
    "DTC_XSDS",
    "EVENT_FACT_PROVENANCE",
    "PROFILES",
    "AccountDefault",
    "AccountReconciliation",
    "AdapterRefusalError",
    "AdapterRefusalReason",
    "CashMovement",
    "CorporateActionBreakCode",
    "CorporateActionEvent",
    "CorporateActionEventRecord",
    "CorporateActionReconciliation",
    "DefaultAssignment",
    "DefaultAssignmentBody",
    "DefaultRefusal",
    "DtcPackage",
    "DtcXsd",
    "ElectionBody",
    "ElectionBook",
    "ElectionEntry",
    "ElectionInstruction",
    "ElectionOption",
    "ElectionPolicy",
    "ElectionRefusal",
    "EncodedMessage",
    "EntitlementResult",
    "EventDates",
    "EventTerms",
    "EventType",
    "HolderEntitlement",
    "HolderPosition",
    "JournalMismatchError",
    "Lifecycle",
    "LifecycleState",
    "LifecycleStatus",
    "LifecycleTransitionBody",
    "MessageFamily",
    "MessageProfile",
    "Milestone",
    "MovementBalances",
    "MovementReport",
    "OptionType",
    "Participation",
    "ProtectCover",
    "ReconciliationBody",
    "RecordBody",
    "RefusalReason",
    "Release",
    "SecuritiesMovement",
    "SourceIdentity",
    "Submission",
    "TransitionEntry",
    "TransitionRequest",
    "UnavailableTreatment",
    "assign_defaults",
    "compute_entitlements",
    "decode_announcement",
    "decode_instruction",
    "decode_movement",
    "encode_announcement",
    "encode_instruction",
    "encode_movement",
    "firm_deadline",
    "rebuild",
    "rebuild_elections",
    "rebuild_elections_from_records",
    "rebuild_from_records",
    "reconcile",
    "record_defaults",
    "record_reconciliation",
    "record_request",
    "record_submission",
    "verify_reconciliation",
]
