"""Corporate action events: lifecycle, entitlement and their DSOR records (ORDER SC-1).

EXPERIMENTAL (charter section 18.6). Nothing here is production evidence, and
nothing here transmits. Atreides prepares; an entitled member submits.

- :mod:`~atreides.corporate_actions.events`: the event as announced, its dates
  and terms, and who reported it.
- :mod:`~atreides.corporate_actions.lifecycle`: which milestones may follow
  which, the journal of requests, and rebuilding a lifecycle from it.
- :mod:`~atreides.corporate_actions.record`: the DSOR-admissible record of each
  request.

This package reconciles and does not invent. Where a depository states a
condition but not its treatment, the treatment is refused by name rather than
supplied (see :func:`atreides.rails.cns.absent_entitlement_treatment`).
"""

from atreides.corporate_actions.events import (
    EVENT_FACT_PROVENANCE,
    CorporateActionEvent,
    EventDates,
    EventTerms,
    EventType,
    Participation,
    SourceIdentity,
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
from atreides.corporate_actions.record import (
    CorporateActionEventRecord,
    LifecycleTransitionBody,
    rebuild_from_records,
    record_request,
)

__all__ = [
    "EVENT_FACT_PROVENANCE",
    "CorporateActionEvent",
    "CorporateActionEventRecord",
    "EventDates",
    "EventTerms",
    "EventType",
    "JournalMismatchError",
    "Lifecycle",
    "LifecycleState",
    "LifecycleStatus",
    "LifecycleTransitionBody",
    "Milestone",
    "Participation",
    "RefusalReason",
    "SourceIdentity",
    "TransitionEntry",
    "TransitionRequest",
    "rebuild",
    "rebuild_from_records",
    "record_request",
]
