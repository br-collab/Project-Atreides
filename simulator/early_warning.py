"""Synthetic Rule 17a-11 early-warning draft workflow with no transmission seam."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from cannae_kernel.actor import ActorRef

from atreides.account_lifecycle import ApproverVerifier
from atreides.customer_protection.net_capital import EarlyWarning

RULE_CHECKSUM = "612026da8c0226c20f137de0f72362610d7cbb3fd8a87e904f048363e3eea475"
DEADLINE_QUOTE = (
    "Every broker or dealer must send notice promptly (but within 24 hours) after the "
    "occurrence of the events specified in paragraphs (b)(1) through (5) of this section "
    "in accordance with paragraph (h) of this section:"
)
PARAGRAPH_QUOTES = {
    "17a-11(b)(1)": (
        "If a computation made by a broker or dealer subject to the aggregate indebtedness "
        "standard of § 240.15c3-1 shows that its aggregate indebtedness is in excess of "
        "1,200 percent of its net capital; or"
    ),
    "17a-11(b)(2)": (
        "If a computation made by a broker or dealer, which has elected the alternative "
        "standard of § 240.15c3-1, shows that its net capital is less than 5 percent of "
        "aggregate debit items computed in accordance with § 240.15c3-3a Exhibit A: Formula "
        "for Determination Reserve Requirement of Brokers and Dealers under § 240.15c3-3; or"
    ),
    "17a-11(b)(3)": (
        "If a computation made by a broker or dealer pursuant to § 240.15c3-1 shows that its "
        "total net capital is less than 120 percent of the broker's or dealer's required "
        "minimum net capital, or if a computation made by an OTC derivatives dealer pursuant "
        "to § 240.15c3-1 shows that its total tentative net capital is less than 120 percent "
        "of the dealer's required minimum tentative net capital."
    ),
    "17a-11(b)(5)": (
        "If a computation made by a broker or dealer pursuant to § 240.15c3-1 shows that the "
        "total amount of money payable against all securities loaned or subject to a "
        "repurchase agreement or the total contract value of all securities borrowed or "
        "subject to a reverse repurchase agreement is in excess of 2500 percent of its "
        "tentative net capital; provided, however, that for purposes of this leverage test "
        "transactions involving government securities, as defined in section 3(a)(42) of "
        "the Act (15 U.S.C. 78c(a)(42)), must be excluded from the calculation; provided "
        "further, however, that a broker or dealer will not be required to send the notice "
        "required by this paragraph (c)(5) if it reports monthly its securities lending and "
        "borrowing and repurchase and reverse repurchase activity (including the total amount "
        "of money payable against securities loaned or subject to a repurchase agreement and "
        "the total contract value of securities borrowed or subject to a reverse repurchase "
        "agreement) to its designated examining authority in a form acceptable to its "
        "designated examining authority."
    ),
}


@dataclass(frozen=True, slots=True)
class EarlyWarningNotice:
    notice_id: str
    paragraph: str
    paragraph_quote: str
    deadline_quote: str
    rule_checksum: str
    threshold: Decimal | None
    measure: Decimal | None
    cushion: Decimal | None
    close_date: date
    deadline: datetime
    owner_role: Literal["FINOP"] | None
    label: Literal["synthetic draft, not filed"] = "synthetic draft, not filed"
    transmitted: Literal[False] = False
    status: Literal["PENDING", "ACKNOWLEDGED", "COMPUTATION_CORRECTED"] = "PENDING"
    decision_actor_id: str | None = None
    decision_time: datetime | None = None


def draft_notices(
    warnings: tuple[EarlyWarning, ...], close_date: date
) -> tuple[EarlyWarningNotice, ...]:
    """Create owned internal drafts for every observed triggered Rule 17a-11 indicator."""
    close_time = datetime.combine(close_date, time(21), tzinfo=UTC)
    return tuple(
        EarlyWarningNotice(
            notice_id=f"SYN-17A11-{close_date.isoformat()}-{index}",
            paragraph=warning.paragraph,
            paragraph_quote=PARAGRAPH_QUOTES[warning.paragraph],
            deadline_quote=DEADLINE_QUOTE,
            rule_checksum=RULE_CHECKSUM,
            threshold=warning.threshold,
            measure=warning.measure,
            cushion=warning.cushion,
            close_date=close_date,
            deadline=close_time + timedelta(hours=24),
            owner_role="FINOP",
        )
        for index, warning in enumerate(warnings, start=1)
        if warning.triggered is True
    )


def warning_workflow_held(
    warnings: tuple[EarlyWarning, ...], notices: tuple[EarlyWarningNotice, ...]
) -> bool:
    triggered = {warning.paragraph for warning in warnings if warning.triggered is True}
    noticed = {notice.paragraph for notice in notices}
    return triggered == noticed and len(triggered) == len(notices) and all(
        notice.owner_role == "FINOP"
        and notice.label == "synthetic draft, not filed"
        and notice.transmitted is False
        for notice in notices
    )


class EarlyWarningQueue:
    """In-memory human queue for synthetic drafts; it has no send or transmit method."""

    def __init__(
        self, notices: tuple[EarlyWarningNotice, ...], verifier: ApproverVerifier
    ) -> None:
        self._notices = {notice.notice_id: notice for notice in notices}
        self._verifier = verifier

    @property
    def notices(self) -> tuple[EarlyWarningNotice, ...]:
        return tuple(self._notices[key] for key in sorted(self._notices))

    def decide(
        self,
        notice_id: str,
        decision: Literal["ACKNOWLEDGE", "CORRECT_COMPUTATION"],
        *,
        actor: ActorRef,
        approval_ref: str,
        decided_at: datetime,
    ) -> EarlyWarningNotice:
        if actor.role != "FINOP" or not self._verifier.is_verified_human(actor, approval_ref):
            raise PermissionError("EARLY_WARNING_DECISION_REQUIRES_VERIFIED_HUMAN")
        current = self._notices[notice_id]
        if current.status != "PENDING":
            raise ValueError("EARLY_WARNING_DRAFT_ALREADY_DECIDED")
        updated = replace(
            current,
            status=(
                "ACKNOWLEDGED" if decision == "ACKNOWLEDGE" else "COMPUTATION_CORRECTED"
            ),
            decision_actor_id=str(actor.actor_id),
            decision_time=decided_at,
        )
        self._notices[notice_id] = updated
        return updated
