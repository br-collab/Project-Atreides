"""Typed FICC Government Securities Division participant access relationships.

This module models *who acts through whose membership or agency*. It does not
authorize, submit, novate, net, settle, or establish finality.

The governing source is the effective FICC GSD Rulebook and procedures supplied
by the caller. DTCC product pages are orientation only; the Rulebook governs.
Rule versions, processing calendars, authority evidence, and novation evidence
are therefore required inputs rather than constants inferred from timestamps.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "AccessArrangement",
    "AccessDetermination",
    "AccessPath",
    "AccessStatus",
    "AuthorityEvidence",
    "NovationEvidence",
    "PartyRef",
    "PartyRole",
    "indeterminate_access",
]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class AccessPath(StrEnum):
    """Supported direct and indirect GSD access relationships."""

    FICC_DIRECT = "FICC_DIRECT"
    FICC_SPONSORED = "FICC_SPONSORED"
    FICC_AGENT = "FICC_AGENT"


class PartyRole(StrEnum):
    """A party's role in one access arrangement, not a general entitlement."""

    DIRECT_NETTING_MEMBER = "DIRECT_NETTING_MEMBER"
    SPONSORED_MEMBER = "SPONSORED_MEMBER"
    SPONSORING_MEMBER = "SPONSORING_MEMBER"
    EXECUTING_FIRM_CUSTOMER = "EXECUTING_FIRM_CUSTOMER"
    AGENT_CLEARING_MEMBER = "AGENT_CLEARING_MEMBER"
    CENTRAL_COUNTERPARTY = "CENTRAL_COUNTERPARTY"


class AccessStatus(StrEnum):
    ESTABLISHED = "ESTABLISHED"
    INDETERMINATE = "INDETERMINATE"


class PartyRef(_Model):
    party_id: str = Field(min_length=1)
    role: PartyRole


class AuthorityEvidence(_Model):
    """Evidence that one party may rely on the stated membership or agency."""

    evidence_id: str = Field(min_length=1)
    principal_party_id: str = Field(min_length=1)
    authority_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class NovationEvidence(_Model):
    """The rule-defined event used later to establish novation as a fact."""

    event_name: str = Field(min_length=1)
    rule_reference: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)


class AccessArrangement(_Model):
    """An established GSD access relationship with no effectful behavior."""

    path: AccessPath
    acting_party: PartyRef
    clearing_member: PartyRef
    intermediary: PartyRef | None = None
    ficc: PartyRef
    authority_evidence: tuple[AuthorityEvidence, ...] = Field(min_length=1)
    novation_evidence: NovationEvidence
    rule_set_version: str = Field(min_length=1)
    processing_calendar_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _path_roles_and_authority_are_explicit(self) -> Self:
        if self.ficc.role is not PartyRole.CENTRAL_COUNTERPARTY:
            raise ValueError("ficc must carry the CENTRAL_COUNTERPARTY role")

        required_principals: set[str]
        if self.path is AccessPath.FICC_DIRECT:
            if self.acting_party.role is not PartyRole.DIRECT_NETTING_MEMBER:
                raise ValueError("FICC_DIRECT requires a DIRECT_NETTING_MEMBER acting party")
            if self.clearing_member != self.acting_party:
                raise ValueError("FICC_DIRECT acting party must be the clearing member")
            if self.intermediary is not None:
                raise ValueError("FICC_DIRECT has no indirect intermediary")
            required_principals = {self.acting_party.party_id}
        elif self.path is AccessPath.FICC_SPONSORED:
            if self.acting_party.role is not PartyRole.SPONSORED_MEMBER:
                raise ValueError("FICC_SPONSORED requires a SPONSORED_MEMBER acting party")
            if (
                self.intermediary is None
                or self.intermediary.role is not PartyRole.SPONSORING_MEMBER
            ):
                raise ValueError("FICC_SPONSORED requires a SPONSORING_MEMBER intermediary")
            if self.clearing_member != self.intermediary:
                raise ValueError("the sponsoring member must be the relied-on clearing member")
            required_principals = {self.acting_party.party_id, self.intermediary.party_id}
        else:
            if self.acting_party.role is not PartyRole.EXECUTING_FIRM_CUSTOMER:
                raise ValueError("FICC_AGENT requires an EXECUTING_FIRM_CUSTOMER acting party")
            if (
                self.intermediary is None
                or self.intermediary.role is not PartyRole.AGENT_CLEARING_MEMBER
            ):
                raise ValueError("FICC_AGENT requires an AGENT_CLEARING_MEMBER intermediary")
            if self.clearing_member != self.intermediary:
                raise ValueError("the agent clearing member must be the relied-on clearing member")
            required_principals = {self.acting_party.party_id, self.intermediary.party_id}

        evidenced = {item.principal_party_id for item in self.authority_evidence}
        missing = required_principals - evidenced
        if missing:
            raise ValueError(f"authority evidence missing for principals: {sorted(missing)}")
        return self


class AccessDetermination(_Model):
    """An established arrangement or an explicit reason it is not established."""

    status: AccessStatus
    arrangement: AccessArrangement | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _status_matches_evidence(self) -> Self:
        if self.status is AccessStatus.ESTABLISHED:
            if self.arrangement is None or self.reason is not None:
                raise ValueError("ESTABLISHED requires an arrangement and no absence reason")
        elif self.arrangement is not None or not self.reason:
            raise ValueError("INDETERMINATE requires a reason and no arrangement")
        return self


def indeterminate_access(reason: str) -> AccessDetermination:
    """Return explicit absence without inventing a default access path."""

    return AccessDetermination(status=AccessStatus.INDETERMINATE, reason=reason)
