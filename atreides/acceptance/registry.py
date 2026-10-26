"""Attested participant reference data: which BIC stands behind which cash account.

INST-1 Amendment 3 (WP2b). An instruction's debtor and creditor are compared with the
obligation's cash accounts through this registry. A registry is reference data, so it is
versioned and digested, and the obligation payload names the digest of the version L.C.
formed it against (``ObligationCandidate.participant_registry_digest``). A caller cannot
substitute a convenient mapping: a registry whose digest differs is refused.
"""

from __future__ import annotations

from dataclasses import dataclass

from cannae_kernel.canonical import canonical_bytes_of, digest_bytes

from atreides.messaging.canonical import FinancialInstitution

__all__ = ["ParticipantRegistry"]


@dataclass(frozen=True)
class ParticipantRegistry:
    """One version of the account-to-institution mapping."""

    version: str
    entries: tuple[tuple[str, FinancialInstitution], ...]

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("a participant registry needs a version")
        accounts = [account for account, _ in self.entries]
        if len(accounts) != len(set(accounts)):
            raise ValueError("a participant registry maps each account once")
        if any(not account for account in accounts):
            raise ValueError("a participant registry account id cannot be empty")

    @property
    def digest(self) -> str:
        """``sha256:`` digest over the version and the sorted entries."""
        body = {
            "version": self.version,
            "entries": [
                [account, institution.bicfi, institution.name or ""]
                for account, institution in sorted(self.entries, key=lambda item: item[0])
            ],
        }
        return digest_bytes(canonical_bytes_of(body))

    def institution(self, account_id: str | None) -> FinancialInstitution | None:
        if account_id is None:
            return None
        return next((inst for account, inst in self.entries if account == account_id), None)
