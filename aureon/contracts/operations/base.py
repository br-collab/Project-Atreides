"""Base custody operation with the four architectural cross-validators.

Per AUR-CUSTODY-001 v1.0 Sections IV (object inventory), V (transaction
types and settlement methods), VII (quorum authority), VIII (failure-
mode taxonomy), IX (inherent-safety architecture).

The base ``CustodyOperation`` carries:

- ``lineage`` — the DSOR lineage stub (operation id, doctrine version,
  authority tier, pre/post hashes, etc.) per AUR-CANONICAL-001 v1.6
  Axiom 1.
- ``custody_object`` — the discriminated-union custody object
  (ordinary safekeeping, pledged, SMA, tokenized, native digital).
- ``failure_mode_class`` — the four-class custody-specific taxonomy
  (RA / RM / UR-R / UR-F) per AUR-CUSTODY-001 v1.0 Section VIII.
- ``inherent_safety_surface`` — the inherent-safety surface declaration
  per AUR-CUSTODY-001 v1.0 Section IX. ``None`` when the operation is
  not on an inherent-safety surface.
- ``quorum_authority`` — the typed quorum-ceremony record per
  AUR-CUSTODY-001 v1.0 Section VII. ``None`` when the operation does
  not require quorum routing.
- ``settlement_method`` — the settlement method per Section V. ``None``
  for operations that have no settlement leg (e.g., key ceremonies,
  cold-storage entry, beneficial-owner identity changes).
- ``kind`` — discriminator for the per-asset-class operation models
  (declared as ``Literal[...]`` in subclasses).

Four architectural cross-validators:

1. **UR-F → inherent-safety surface required.** Per
   AUR-CUSTODY-001 v1.0 Section VIII: 'Operations tagged UR-F that are
   not on inherent-safety surfaces with quorum authority are doctrine
   integrity gaps and must be either remediated (move to inherent-
   safety surface with quorum authority) or eliminated (operation type
   is not offered).'
2. **Inherent-safety surface → quorum authority required.** Per
   AUR-CUSTODY-001 v1.0 Section IX and AUR-CANONICAL-001 v1.6 Axiom
   10: 'no single authority, no single component, no single signature,
   no single key, no single jurisdiction, and no single counterparty
   may sit on the loss path.' The contracts layer enforces that an
   operation on a declared inherent-safety surface carries a quorum
   authority record.
3. **Inherent-safety surface → authority tier QUORUM.** Per
   AUR-CUSTODY-001 v1.0 Section VII and AUR-CANONICAL-001 v1.6
   Section V: 'A quorum authority operation is one that cannot be
   authorized by any single tier of the CAOM authority structure'.
   The DSOR lineage's authority_tier on an inherent-safety operation
   must be QUORUM, never T0/T1/T2/T3.
4. **Quorum-authority field consistency.** When ``quorum_authority``
   is set, ``lineage.authority_tier`` must be QUORUM, and conversely.
   The two cannot disagree.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aureon.contracts.custody_object import CustodyObject
from aureon.contracts.dsor_stub import CAOMTier, DSORLineageStub
from aureon.contracts.failure_mode import FailureModeClass
from aureon.contracts.inherent_safety import InherentSafetySurface
from aureon.contracts.quorum import QuorumAuthority
from aureon.contracts.settlement import SettlementMethod


class CustodyOperation(BaseModel):
    """Base custody operation type.

    Subclassed by per-asset-class operation models in
    ``aureon.contracts.operations.equity`` and siblings. Each subclass
    overrides ``kind`` with a ``Literal`` value that serves as the
    discriminator in the union exposed at the package level.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    kind: str = Field(description="Discriminator field — overridden in subclasses.")
    lineage: DSORLineageStub = Field(
        description=(
            "DSOR lineage stub. Carries operation id, doctrine version, "
            "authority tier and id, pre/post state hashes."
        ),
    )
    custody_object: CustodyObject = Field(
        description="The custody object the operation acts upon.",
    )
    failure_mode_class: FailureModeClass = Field(
        description=(
            "Failure-mode classification per AUR-CUSTODY-001 v1.0 "
            "Section VIII. Operations declared UR-F must also declare "
            "an inherent-safety surface."
        ),
    )
    inherent_safety_surface: InherentSafetySurface | None = Field(
        default=None,
        description=(
            "Inherent-safety surface declaration per AUR-CUSTODY-001 "
            "v1.0 Section IX. None when the operation is not on an "
            "inherent-safety surface."
        ),
    )
    quorum_authority: QuorumAuthority | None = Field(
        default=None,
        description=(
            "Quorum authority ceremony record per AUR-CUSTODY-001 v1.0 "
            "Section VII. Required when inherent_safety_surface is "
            "set; None otherwise."
        ),
    )
    settlement_method: SettlementMethod | None = Field(
        default=None,
        description=(
            "Settlement method per AUR-CUSTODY-001 v1.0 Section V. "
            "None for operations that have no settlement leg "
            "(key ceremonies, cold-storage entry, beneficial owner "
            "identity changes)."
        ),
    )

    @model_validator(mode="after")
    def _validate_ur_f_requires_inherent_safety(self) -> Self:
        """Per AUR-CUSTODY-001 v1.0 Section VIII: UR-F operations on
        non-inherent-safety surfaces are doctrine integrity gaps."""
        if (
            self.failure_mode_class.is_final
            and self.inherent_safety_surface is None
        ):
            raise ValueError(
                "Per AUR-CUSTODY-001 v1.0 Section VIII, operations "
                "classified UR-F must declare an inherent-safety "
                "surface (Axiom 8 doctrine integrity gap if not). "
                "Either move the operation to an inherent-safety "
                "surface with quorum authority, or eliminate the "
                "operation type."
            )
        return self

    @model_validator(mode="after")
    def _validate_inherent_safety_requires_quorum(self) -> Self:
        """Per AUR-CUSTODY-001 v1.0 Section IX and AUR-CANONICAL-001
        v1.6 Axiom 10: inherent-safety surfaces require quorum
        authority routing."""
        if (
            self.inherent_safety_surface is not None
            and self.quorum_authority is None
        ):
            raise ValueError(
                f"Per AUR-CUSTODY-001 v1.0 Section IX and "
                f"AUR-CANONICAL-001 v1.6 Axiom 10, operations on "
                f"inherent-safety surface "
                f"{self.inherent_safety_surface.value!r} require "
                f"quorum_authority routing (no single authority on the "
                f"loss path)."
            )
        return self

    @model_validator(mode="after")
    def _validate_inherent_safety_authority_tier_is_quorum(self) -> Self:
        """Per AUR-CUSTODY-001 v1.0 Section VII and AUR-CANONICAL-001
        v1.6 Section V: a quorum-required operation cannot be
        authorized by any single CAOM tier."""
        if (
            self.inherent_safety_surface is not None
            and self.lineage.authority_tier is not CAOMTier.QUORUM
        ):
            raise ValueError(
                f"Per AUR-CUSTODY-001 v1.0 Section VII, operations on "
                f"inherent-safety surface "
                f"{self.inherent_safety_surface.value!r} must carry "
                f"DSOR lineage with authority_tier=QUORUM, got "
                f"{self.lineage.authority_tier.value!r}."
            )
        return self

    @model_validator(mode="after")
    def _validate_quorum_field_consistency(self) -> Self:
        """The ``quorum_authority`` field and the lineage's
        ``authority_tier == QUORUM`` must agree.

        Either both are set (authority_tier is QUORUM and a
        quorum_authority record is present) or neither (any other
        authority_tier with no quorum_authority record).
        """
        has_quorum_record = self.quorum_authority is not None
        is_quorum_tier = self.lineage.authority_tier is CAOMTier.QUORUM
        if has_quorum_record and not is_quorum_tier:
            raise ValueError(
                "When quorum_authority is set, the DSOR lineage's "
                "authority_tier must be QUORUM (a single CAOM tier "
                "cannot satisfy a quorum-required operation per "
                "AUR-CANONICAL-001 v1.6 Section V)."
            )
        if is_quorum_tier and not has_quorum_record:
            raise ValueError(
                "When DSOR lineage authority_tier is QUORUM, the "
                "operation must carry a quorum_authority ceremony "
                "record per AUR-CUSTODY-001 v1.0 Section VII."
            )
        return self


__all__ = ["CustodyOperation"]
