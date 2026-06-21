"""Tests for ``aureon.contracts.quorum``.

Per AUR-CUSTODY-001 v1.0 Section VII (Quorum Authority Operational
Specification).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from aureon.contracts.quorum import (
    DEFAULT_THRESHOLD_M,
    DEFAULT_THRESHOLD_N,
    CeremonyState,
    CeremonyStep,
    IndependenceRequirement,
    QuorumAuthority,
    QuorumThreshold,
    Signature,
    SigningAuthority,
)


def _make_pool(
    *,
    distinct_identities: bool = True,
    distinct_orgs: bool = True,
    distinct_jurisdictions: bool = True,
    distinct_systems: bool = True,
    size: int = DEFAULT_THRESHOLD_M,
) -> tuple[SigningAuthority, ...]:
    """Build a 5-member signing pool, parametrically toggling
    independence dimensions for negative-test coverage.

    The pool members span ops/risk/compliance/treasury/audit, two
    jurisdictions (US/UK), and five distinct signing systems by
    default — all four pool-level independence requirements satisfied.
    """
    org_options = [
        "operations",
        "risk",
        "compliance",
        "treasury",
        "audit",
    ]
    jurisdiction_options = ["US", "UK", "US", "UK", "US"]
    system_options = [f"hsm-{i}" for i in range(size)]
    return tuple(
        SigningAuthority(
            authority_id=f"auth-{i}",
            identity_id=(
                f"person-{i}" if distinct_identities else "person-shared"
            ),
            organizational_unit=(
                org_options[i % len(org_options)]
                if distinct_orgs
                else "operations"
            ),
            jurisdiction=(
                jurisdiction_options[i] if distinct_jurisdictions else "US"
            ),
            signing_system=(
                system_options[i] if distinct_systems else "hsm-shared"
            ),
        )
        for i in range(size)
    )


class TestThresholdDefaults:
    def test_default_is_three_of_five(self) -> None:
        # Per AUR-CUSTODY-001 v1.0 Section VII default threshold.
        threshold = QuorumThreshold()
        assert threshold.n == DEFAULT_THRESHOLD_N
        assert threshold.m == DEFAULT_THRESHOLD_M

    def test_constants_match_doctrine_default(self) -> None:
        # The constants are part of the contract surface — agents
        # depend on the named default.
        assert DEFAULT_THRESHOLD_N == 3  # noqa: PLR2004
        assert DEFAULT_THRESHOLD_M == 5  # noqa: PLR2004


class TestThresholdValidation:
    def test_n_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            QuorumThreshold(n=0, m=3)

    def test_m_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            QuorumThreshold(n=1, m=0)

    def test_n_exceeding_m_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not exceed M"):
            QuorumThreshold(n=6, m=5)

    @pytest.mark.parametrize(
        ("n", "m"),
        [
            (2, 3),
            (3, 5),
            (4, 5),
            (4, 6),
            (5, 7),
        ],
    )
    def test_doctrinal_threshold_ranges_accepted(
        self, n: int, m: int
    ) -> None:
        # Ranges named in Section VII: 2-of-3, 3-of-5 (default), 4-of-5,
        # 4-of-6, 5-of-7.
        threshold = QuorumThreshold(n=n, m=m)
        assert threshold.n == n
        assert threshold.m == m


class TestQuorumAuthorityConstruction:
    def test_minimal_valid_construction(self) -> None:
        authority = QuorumAuthority(
            independence_requirements=frozenset(),
            signing_pool=_make_pool(),
        )
        assert authority.threshold.n == DEFAULT_THRESHOLD_N
        assert authority.ceremony_state is CeremonyState.PENDING
        assert authority.ceremony_step is CeremonyStep.PACKAGE_ASSEMBLY

    def test_pool_size_must_match_m(self) -> None:
        with pytest.raises(
            ValidationError, match=r"must equal threshold\.m"
        ):
            QuorumAuthority(
                threshold=QuorumThreshold(n=3, m=5),
                independence_requirements=frozenset(),
                signing_pool=_make_pool(size=4),
            )

    def test_duplicate_authority_ids_rejected(self) -> None:
        pool = (
            SigningAuthority(
                authority_id="auth-dup",
                identity_id="person-1",
                organizational_unit="operations",
                jurisdiction="US",
                signing_system="hsm-1",
            ),
            SigningAuthority(
                authority_id="auth-dup",
                identity_id="person-2",
                organizational_unit="risk",
                jurisdiction="UK",
                signing_system="hsm-2",
            ),
            *_make_pool(size=3),
        )
        with pytest.raises(ValidationError, match="unique authority_id"):
            QuorumAuthority(
                independence_requirements=frozenset(),
                signing_pool=pool,
            )


class TestSignatureRules:
    def test_signature_must_reference_pool_member(self) -> None:
        with pytest.raises(
            ValidationError, match="not in the signing pool"
        ):
            QuorumAuthority(
                independence_requirements=frozenset(),
                signing_pool=_make_pool(),
                collected_signatures=(
                    Signature(
                        authority_id="auth-not-in-pool",
                        signed_at=datetime.now(UTC),
                    ),
                ),
            )

    def test_double_signing_rejected(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(
            ValidationError,
            match="more than one signature",
        ):
            QuorumAuthority(
                independence_requirements=frozenset(),
                signing_pool=_make_pool(),
                collected_signatures=(
                    Signature(authority_id="auth-0", signed_at=now),
                    Signature(
                        authority_id="auth-0",
                        signed_at=now + timedelta(hours=1),
                    ),
                ),
            )

    def test_signatures_exceeding_threshold_rejected(self) -> None:
        # threshold.n = 3, four signatures collected → reject
        now = datetime.now(UTC)
        with pytest.raises(
            ValidationError, match=r"must not exceed threshold\.n"
        ):
            QuorumAuthority(
                independence_requirements=frozenset(),
                signing_pool=_make_pool(),
                collected_signatures=tuple(
                    Signature(
                        authority_id=f"auth-{i}",
                        signed_at=now + timedelta(hours=i),
                    )
                    for i in range(4)
                ),
            )

    def test_completed_state_requires_exact_n_signatures(self) -> None:
        now = datetime.now(UTC)
        # COMPLETED with only 2 signatures (threshold.n = 3) → reject.
        with pytest.raises(
            ValidationError, match="COMPLETED ceremony must have exactly"
        ):
            QuorumAuthority(
                independence_requirements=frozenset(),
                signing_pool=_make_pool(),
                collected_signatures=tuple(
                    Signature(
                        authority_id=f"auth-{i}",
                        signed_at=now + timedelta(hours=i),
                    )
                    for i in range(2)
                ),
                ceremony_state=CeremonyState.COMPLETED,
            )

    def test_completed_state_with_exact_n_signatures_accepted(self) -> None:
        now = datetime.now(UTC)
        authority = QuorumAuthority(
            independence_requirements=frozenset(),
            signing_pool=_make_pool(),
            collected_signatures=tuple(
                Signature(
                    authority_id=f"auth-{i}",
                    signed_at=now + timedelta(hours=i),
                )
                for i in range(DEFAULT_THRESHOLD_N)
            ),
            ceremony_state=CeremonyState.COMPLETED,
            ceremony_step=CeremonyStep.OPERATION_EXECUTION,
        )
        assert len(authority.collected_signatures) == DEFAULT_THRESHOLD_N


class TestIdentityIndependence:
    def test_satisfied_when_identities_distinct(self) -> None:
        QuorumAuthority(
            independence_requirements=frozenset(
                {IndependenceRequirement.IDENTITY}
            ),
            signing_pool=_make_pool(distinct_identities=True),
        )

    def test_violated_when_identities_shared(self) -> None:
        with pytest.raises(
            ValidationError, match="identity independence"
        ):
            QuorumAuthority(
                independence_requirements=frozenset(
                    {IndependenceRequirement.IDENTITY}
                ),
                signing_pool=_make_pool(distinct_identities=False),
            )


class TestOrganizationalIndependence:
    def test_satisfied_when_orgs_distinct(self) -> None:
        QuorumAuthority(
            independence_requirements=frozenset(
                {IndependenceRequirement.ORGANIZATIONAL}
            ),
            signing_pool=_make_pool(distinct_orgs=True),
        )

    def test_violated_when_orgs_shared(self) -> None:
        with pytest.raises(
            ValidationError, match="organizational independence"
        ):
            QuorumAuthority(
                independence_requirements=frozenset(
                    {IndependenceRequirement.ORGANIZATIONAL}
                ),
                signing_pool=_make_pool(distinct_orgs=False),
            )


class TestGeographicIndependence:
    def test_satisfied_when_jurisdictions_distinct(self) -> None:
        QuorumAuthority(
            independence_requirements=frozenset(
                {IndependenceRequirement.GEOGRAPHIC}
            ),
            signing_pool=_make_pool(distinct_jurisdictions=True),
        )

    def test_violated_when_jurisdictions_shared(self) -> None:
        with pytest.raises(
            ValidationError, match="geographic independence"
        ):
            QuorumAuthority(
                independence_requirements=frozenset(
                    {IndependenceRequirement.GEOGRAPHIC}
                ),
                signing_pool=_make_pool(distinct_jurisdictions=False),
            )


class TestSystemIndependence:
    def test_satisfied_when_systems_distinct(self) -> None:
        QuorumAuthority(
            independence_requirements=frozenset(
                {IndependenceRequirement.SYSTEM}
            ),
            signing_pool=_make_pool(distinct_systems=True),
        )

    def test_violated_when_systems_shared(self) -> None:
        with pytest.raises(
            ValidationError, match="system independence"
        ):
            QuorumAuthority(
                independence_requirements=frozenset(
                    {IndependenceRequirement.SYSTEM}
                ),
                signing_pool=_make_pool(distinct_systems=False),
            )


class TestTemporalIndependence:
    def test_temporal_requirement_carried_but_not_enforced_at_contracts(
        self,
    ) -> None:
        """Temporal independence is enforced at ceremony-execution time
        (out of scope for the contracts layer per Section VII). The
        contracts layer accepts the requirement flag and the per-
        signature timestamps; runtime ceremony code enforces interval
        constraints."""
        now = datetime.now(UTC)
        # Two signatures close in time — would fail temporal at runtime
        # but contracts-layer construction succeeds.
        authority = QuorumAuthority(
            independence_requirements=frozenset(
                {IndependenceRequirement.TEMPORAL}
            ),
            signing_pool=_make_pool(),
            collected_signatures=(
                Signature(authority_id="auth-0", signed_at=now),
                Signature(
                    authority_id="auth-1",
                    signed_at=now + timedelta(seconds=1),
                ),
            ),
        )
        assert (
            IndependenceRequirement.TEMPORAL
            in authority.independence_requirements
        )


class TestCeremonyStepCoverage:
    def test_six_steps_enumerated(self) -> None:
        # Per AUR-CUSTODY-001 v1.0 Section VII signature ceremony
        # protocol — six steps.
        assert len(CeremonyStep) == 6  # noqa: PLR2004


class TestCeremonyStateCoverage:
    def test_five_states_enumerated(self) -> None:
        # PENDING / IN_PROGRESS / COMPLETED / FAILED / ESCALATED.
        assert len(CeremonyState) == 5  # noqa: PLR2004


class TestImmutability:
    def test_quorum_authority_is_frozen(self) -> None:
        authority = QuorumAuthority(
            independence_requirements=frozenset(),
            signing_pool=_make_pool(),
        )
        with pytest.raises(ValidationError):
            authority.ceremony_state = CeremonyState.IN_PROGRESS  # type: ignore[misc]
