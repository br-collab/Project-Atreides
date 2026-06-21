"""Failure-mode classification — four-class custody taxonomy.

Per AUR-CANONICAL-001 v1.6 Section VI (three-class framework taxonomy:
RA, RM, UR) and AUR-CUSTODY-001 v1.0 Section VIII (custody-specific
refinement of UR into UR-R and UR-F).

The taxonomy:

- ``RA`` — Recoverable Automatic. System detects, recovers without human
  action; lineage continuous across the event. Examples: settlement-rail
  outage with pre-staged fallback; transient telemetry loss within RTO.
- ``RM`` — Recoverable Manual. System detects, requires explicit human
  action; lineage may carry a flagged gap. Examples: reconciliation break
  requiring investigation; doctrine ambiguity requiring Mentat resolution.
- ``UR_R`` — Unrecoverable but Reversible-via-Other-Means. The custody
  operation cannot itself undo the loss, but external recovery mechanisms
  (insurance, indemnification, regulatory reimbursement,
  industry-mutualised loss-sharing) bound the licensee's economic
  exposure. Examples: settlement to incorrect counterparty with
  enforceable indemnification; LBMA-vault loss covered by specie
  insurance; title dispute resolved through title insurance claim;
  tokenization-issuer error correctable through reissuance with the
  issuer bearing economic loss.
- ``UR_F`` — Unrecoverable and Final. No mechanism (custody-internal or
  external) can undo the loss; licensee economic exposure is the full
  loss amount. Examples: on-chain transaction with finality to an
  unrecoverable address; private-key compromise with active signing
  authority; physical asset destroyed beyond insurance coverage limits;
  smart-contract exploit with no protocol insurance and no enforceable
  recovery; insurance carrier insolvency with state guaranty fund
  exhausted.

The architectural rule that binds the taxonomy to operations is
enforced in ``aureon.contracts.operations`` (UR-F operations on
non-inherent-safety surfaces are doctrine integrity gaps under
AUR-CUSTODY-001 v1.0 Section VIII; this module defines the taxonomy
itself).
"""

from __future__ import annotations

from enum import StrEnum


class FailureModeClass(StrEnum):
    """Four-class custody-specific failure-mode taxonomy.

    Per AUR-CUSTODY-001 v1.0 Section VIII, refining the three-class
    canonical taxonomy (AUR-CANONICAL-001 v1.6 Section VI) by splitting
    UR into UR-R (recoverable through external mechanisms) and UR-F
    (final, no recovery mechanism).
    """

    RA = "RA"
    RM = "RM"
    UR_R = "UR-R"
    UR_F = "UR-F"

    @property
    def is_unrecoverable(self) -> bool:
        """True for UR-R and UR-F.

        Per AUR-CANONICAL-001 v1.6 Axiom 10, unrecoverable failures must
        not be reachable on inherent-safety surfaces. Operations
        downstream use this property when applying the architectural
        rule.
        """
        return self in {FailureModeClass.UR_R, FailureModeClass.UR_F}

    @property
    def is_final(self) -> bool:
        """True for UR-F only.

        Per AUR-CUSTODY-001 v1.0 Section VIII, UR-F operations are the
        ones that demand inherent-safety-surface placement with quorum
        authority. UR-R operations have bounded licensee economic
        exposure through external recovery and do not by themselves
        force an inherent-safety placement.
        """
        return self is FailureModeClass.UR_F


__all__ = ["FailureModeClass"]
