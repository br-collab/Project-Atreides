"""Tests for the FIAT Operations Specialist eligibility verifier.

Coverage standard matches the contracts layer: every model has positive
and negative tests for every validator; the public ``verify_eligibility``
is exercised against pass/fail variants for each of the five checks
(KYC/KYB/OFAC/sanctions/correspondent-bank-compliance).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from aureon.agents.tier2.eligibility import (
    CorrespondentBankComplianceEvidence,
    EligibilityInputs,
    KYBEvidence,
    KYCEvidence,
    OFACScreeningEvidence,
    SanctionsScreeningEvidence,
    verify_eligibility,
)
from aureon.agents.tier2.outputs import (
    EligibilityCheck,
    EligibilityCheckKind,
    EligibilityVerification,
)

# ---------------------------------------------------------------------------
# Time helpers and fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def check_time() -> datetime:
    return datetime(2026, 5, 3, 14, 0, 0, tzinfo=UTC)


@pytest.fixture
def kyc_current(check_time: datetime) -> KYCEvidence:
    return KYCEvidence(
        beneficial_owner_id="bo-pension-fund-x",
        kyc_reference_id="kyc-2026-001",
        verified_at=check_time - timedelta(days=30),
        expires_at=check_time + timedelta(days=335),
    )


@pytest.fixture
def kyc_expired(check_time: datetime) -> KYCEvidence:
    return KYCEvidence(
        beneficial_owner_id="bo-pension-fund-x",
        kyc_reference_id="kyc-2025-001",
        verified_at=check_time - timedelta(days=400),
        expires_at=check_time - timedelta(days=1),
    )


@pytest.fixture
def kyb_current(check_time: datetime) -> KYBEvidence:
    return KYBEvidence(
        counterparty_entity_id="cp-jpmorgan",
        kyb_reference_id="kyb-2026-001",
        verified_at=check_time - timedelta(days=15),
        expires_at=check_time + timedelta(days=350),
    )


@pytest.fixture
def kyb_expired(check_time: datetime) -> KYBEvidence:
    return KYBEvidence(
        counterparty_entity_id="cp-jpmorgan",
        kyb_reference_id="kyb-2025-001",
        verified_at=check_time - timedelta(days=400),
        expires_at=check_time - timedelta(days=10),
    )


def _ofac_clear(subject_id: str, when: datetime) -> OFACScreeningEvidence:
    return OFACScreeningEvidence(
        subject_id=subject_id,
        screening_id=f"ofac-{subject_id}",
        matched=False,
        screened_at=when,
    )


def _ofac_match(subject_id: str, when: datetime) -> OFACScreeningEvidence:
    return OFACScreeningEvidence(
        subject_id=subject_id,
        screening_id=f"ofac-{subject_id}",
        matched=True,
        matched_list="SDN",
        screened_at=when,
    )


def _sanctions_clear(subject_id: str, when: datetime) -> SanctionsScreeningEvidence:
    return SanctionsScreeningEvidence(
        subject_id=subject_id,
        screening_id=f"sanc-{subject_id}",
        matched=False,
        screened_at=when,
    )


def _sanctions_match(subject_id: str, when: datetime) -> SanctionsScreeningEvidence:
    return SanctionsScreeningEvidence(
        subject_id=subject_id,
        screening_id=f"sanc-{subject_id}",
        matched=True,
        matched_list="EU",
        screened_at=when,
    )


def _correspondent_current(
    bic: str,
    when: datetime,
) -> CorrespondentBankComplianceEvidence:
    return CorrespondentBankComplianceEvidence(
        correspondent_bic=bic,
        attestation_id=f"att-{bic}",
        attested_at=when - timedelta(days=10),
        expires_at=when + timedelta(days=355),
    )


def _correspondent_expired(
    bic: str,
    when: datetime,
) -> CorrespondentBankComplianceEvidence:
    return CorrespondentBankComplianceEvidence(
        correspondent_bic=bic,
        attestation_id=f"att-{bic}-old",
        attested_at=when - timedelta(days=400),
        expires_at=when - timedelta(days=5),
    )


def _check(verification: EligibilityVerification, kind: EligibilityCheckKind) -> EligibilityCheck:
    for c in verification.checks:
        if c.kind is kind:
            return c
    raise AssertionError(f"No check of kind {kind.value!r}")


# ---------------------------------------------------------------------------
# Evidence model validators
# ---------------------------------------------------------------------------


class TestEvidenceModels:
    def test_kyc_constructs_with_minimum_fields(self, check_time: datetime) -> None:
        e = KYCEvidence(
            beneficial_owner_id="bo-1",
            kyc_reference_id="ref-1",
            verified_at=check_time,
            expires_at=check_time + timedelta(days=365),
        )
        assert e.beneficial_owner_id == "bo-1"

    def test_kyc_empty_owner_id_rejected(self, check_time: datetime) -> None:
        with pytest.raises(ValidationError):
            KYCEvidence(
                beneficial_owner_id="",
                kyc_reference_id="ref",
                verified_at=check_time,
                expires_at=check_time + timedelta(days=1),
            )

    def test_kyc_is_frozen(self, kyc_current: KYCEvidence) -> None:
        with pytest.raises(ValidationError):
            kyc_current.beneficial_owner_id = "other"  # type: ignore[misc]

    def test_kyb_constructs(self, kyb_current: KYBEvidence) -> None:
        assert kyb_current.counterparty_entity_id == "cp-jpmorgan"

    def test_ofac_clear_constructs(self, check_time: datetime) -> None:
        e = OFACScreeningEvidence(
            subject_id="bo-1",
            screening_id="s-1",
            matched=False,
            screened_at=check_time,
        )
        assert e.matched_list is None

    def test_ofac_match_requires_matched_list(self, check_time: datetime) -> None:
        with pytest.raises(ValidationError, match="must name the matched_list"):
            OFACScreeningEvidence(
                subject_id="bo-1",
                screening_id="s-1",
                matched=True,
                matched_list=None,
                screened_at=check_time,
            )

    def test_ofac_clear_must_not_carry_matched_list(self, check_time: datetime) -> None:
        with pytest.raises(ValidationError, match="must not carry a matched_list"):
            OFACScreeningEvidence(
                subject_id="bo-1",
                screening_id="s-1",
                matched=False,
                matched_list="SDN",
                screened_at=check_time,
            )

    def test_sanctions_match_requires_matched_list(self, check_time: datetime) -> None:
        with pytest.raises(ValidationError, match="must name the matched_list"):
            SanctionsScreeningEvidence(
                subject_id="bo-1",
                screening_id="s-1",
                matched=True,
                matched_list=None,
                screened_at=check_time,
            )

    def test_sanctions_clear_must_not_carry_matched_list(
        self,
        check_time: datetime,
    ) -> None:
        with pytest.raises(ValidationError, match="must not carry a matched_list"):
            SanctionsScreeningEvidence(
                subject_id="bo-1",
                screening_id="s-1",
                matched=False,
                matched_list="EU",
                screened_at=check_time,
            )

    def test_correspondent_compliance_constructs(self, check_time: datetime) -> None:
        e = CorrespondentBankComplianceEvidence(
            correspondent_bic="CITIUS33",
            attestation_id="att-1",
            attested_at=check_time - timedelta(days=1),
            expires_at=check_time + timedelta(days=364),
        )
        assert e.correspondent_bic == "CITIUS33"

    def test_correspondent_bic_too_short_rejected(self, check_time: datetime) -> None:
        with pytest.raises(ValidationError):
            CorrespondentBankComplianceEvidence(
                correspondent_bic="ABC",
                attestation_id="att-1",
                attested_at=check_time,
                expires_at=check_time + timedelta(days=1),
            )

    def test_correspondent_bic_too_long_rejected(self, check_time: datetime) -> None:
        with pytest.raises(ValidationError):
            CorrespondentBankComplianceEvidence(
                correspondent_bic="ABCDEFGHIJKL",  # 12 chars
                attestation_id="att-1",
                attested_at=check_time,
                expires_at=check_time + timedelta(days=1),
            )


# ---------------------------------------------------------------------------
# EligibilityInputs validators
# ---------------------------------------------------------------------------


class TestEligibilityInputs:
    def test_minimal_inputs_construct(self, check_time: datetime) -> None:
        inputs = EligibilityInputs(check_time=check_time)
        assert inputs.check_time == check_time
        assert inputs.requires_kyb is True

    def test_correspondent_required_without_expected_bics_rejected(
        self,
        check_time: datetime,
    ) -> None:
        with pytest.raises(
            ValidationError,
            match="must name at least one expected correspondent BIC",
        ):
            EligibilityInputs(
                check_time=check_time,
                requires_correspondent_compliance=True,
                expected_correspondent_bics=frozenset(),
            )

    def test_correspondent_required_with_expected_bics_accepted(
        self,
        check_time: datetime,
    ) -> None:
        inputs = EligibilityInputs(
            check_time=check_time,
            requires_correspondent_compliance=True,
            expected_correspondent_bics=frozenset({"CITIUS33"}),
        )
        assert "CITIUS33" in inputs.expected_correspondent_bics


# ---------------------------------------------------------------------------
# verify_eligibility — KYC
# ---------------------------------------------------------------------------


class TestKYCCheck:
    def test_kyc_passes_when_evidence_current(
        self,
        check_time: datetime,
        kyc_current: KYCEvidence,
        kyb_current: KYBEvidence,
    ) -> None:
        inputs = EligibilityInputs(
            check_time=check_time,
            kyc=kyc_current,
            kyb=kyb_current,
            ofac_screenings=(_ofac_clear("bo-pension-fund-x", check_time),),
            sanctions_screenings=(_sanctions_clear("bo-pension-fund-x", check_time),),
        )
        result = verify_eligibility(inputs)
        assert _check(result, EligibilityCheckKind.KYC).passed

    def test_kyc_fails_when_evidence_missing(
        self,
        check_time: datetime,
    ) -> None:
        inputs = EligibilityInputs(check_time=check_time, kyc=None)
        result = verify_eligibility(inputs)
        kyc_check = _check(result, EligibilityCheckKind.KYC)
        assert not kyc_check.passed
        assert "KYC evidence missing" in (kyc_check.failure_reason or "")

    def test_kyc_fails_when_evidence_expired(
        self,
        check_time: datetime,
        kyc_expired: KYCEvidence,
    ) -> None:
        inputs = EligibilityInputs(check_time=check_time, kyc=kyc_expired)
        result = verify_eligibility(inputs)
        kyc_check = _check(result, EligibilityCheckKind.KYC)
        assert not kyc_check.passed
        assert "expired" in (kyc_check.failure_reason or "")


# ---------------------------------------------------------------------------
# verify_eligibility — KYB
# ---------------------------------------------------------------------------


class TestKYBCheck:
    def test_kyb_vacuous_pass_when_not_required(
        self,
        check_time: datetime,
    ) -> None:
        inputs = EligibilityInputs(
            check_time=check_time,
            requires_kyb=False,
            kyb=None,
        )
        result = verify_eligibility(inputs)
        assert _check(result, EligibilityCheckKind.KYB).passed

    def test_kyb_passes_when_evidence_current(
        self,
        check_time: datetime,
        kyb_current: KYBEvidence,
    ) -> None:
        inputs = EligibilityInputs(check_time=check_time, kyb=kyb_current)
        result = verify_eligibility(inputs)
        assert _check(result, EligibilityCheckKind.KYB).passed

    def test_kyb_fails_when_required_and_missing(
        self,
        check_time: datetime,
    ) -> None:
        inputs = EligibilityInputs(check_time=check_time, kyb=None)
        result = verify_eligibility(inputs)
        kyb_check = _check(result, EligibilityCheckKind.KYB)
        assert not kyb_check.passed
        assert "KYB evidence missing" in (kyb_check.failure_reason or "")

    def test_kyb_fails_when_required_and_expired(
        self,
        check_time: datetime,
        kyb_expired: KYBEvidence,
    ) -> None:
        inputs = EligibilityInputs(check_time=check_time, kyb=kyb_expired)
        result = verify_eligibility(inputs)
        kyb_check = _check(result, EligibilityCheckKind.KYB)
        assert not kyb_check.passed
        assert "expired" in (kyb_check.failure_reason or "")


# ---------------------------------------------------------------------------
# verify_eligibility — OFAC
# ---------------------------------------------------------------------------


class TestOFACCheck:
    def test_ofac_passes_when_screening_clear(self, check_time: datetime) -> None:
        inputs = EligibilityInputs(
            check_time=check_time,
            ofac_screenings=(
                _ofac_clear("bo-pension-fund-x", check_time),
                _ofac_clear("cp-jpmorgan", check_time),
            ),
        )
        result = verify_eligibility(inputs)
        assert _check(result, EligibilityCheckKind.OFAC).passed

    def test_ofac_fails_when_no_screening_performed(
        self,
        check_time: datetime,
    ) -> None:
        inputs = EligibilityInputs(check_time=check_time, ofac_screenings=())
        result = verify_eligibility(inputs)
        ofac_check = _check(result, EligibilityCheckKind.OFAC)
        assert not ofac_check.passed
        assert "OFAC screening not performed" in (ofac_check.failure_reason or "")

    def test_ofac_fails_when_screening_matches(self, check_time: datetime) -> None:
        inputs = EligibilityInputs(
            check_time=check_time,
            ofac_screenings=(
                _ofac_clear("bo-pension-fund-x", check_time),
                _ofac_match("cp-sanctioned-entity", check_time),
            ),
        )
        result = verify_eligibility(inputs)
        ofac_check = _check(result, EligibilityCheckKind.OFAC)
        assert not ofac_check.passed
        assert "matched" in (ofac_check.failure_reason or "")
        assert "SDN" in (ofac_check.failure_reason or "")


# ---------------------------------------------------------------------------
# verify_eligibility — Sanctions
# ---------------------------------------------------------------------------


class TestSanctionsCheck:
    def test_sanctions_passes_when_screening_clear(
        self,
        check_time: datetime,
    ) -> None:
        inputs = EligibilityInputs(
            check_time=check_time,
            sanctions_screenings=(
                _sanctions_clear("bo-pension-fund-x", check_time),
            ),
        )
        result = verify_eligibility(inputs)
        assert _check(result, EligibilityCheckKind.SANCTIONS).passed

    def test_sanctions_fails_when_no_screening_performed(
        self,
        check_time: datetime,
    ) -> None:
        inputs = EligibilityInputs(check_time=check_time, sanctions_screenings=())
        result = verify_eligibility(inputs)
        sanc_check = _check(result, EligibilityCheckKind.SANCTIONS)
        assert not sanc_check.passed
        assert "Non-OFAC sanctions screening not performed" in (
            sanc_check.failure_reason or ""
        )

    def test_sanctions_fails_when_screening_matches(
        self,
        check_time: datetime,
    ) -> None:
        inputs = EligibilityInputs(
            check_time=check_time,
            sanctions_screenings=(
                _sanctions_match("cp-eu-sanctioned", check_time),
            ),
        )
        result = verify_eligibility(inputs)
        sanc_check = _check(result, EligibilityCheckKind.SANCTIONS)
        assert not sanc_check.passed
        assert "EU" in (sanc_check.failure_reason or "")


# ---------------------------------------------------------------------------
# verify_eligibility — Correspondent bank compliance
# ---------------------------------------------------------------------------


class TestCorrespondentBankComplianceCheck:
    def test_vacuous_pass_when_not_required(self, check_time: datetime) -> None:
        inputs = EligibilityInputs(
            check_time=check_time,
            requires_correspondent_compliance=False,
        )
        result = verify_eligibility(inputs)
        assert _check(
            result,
            EligibilityCheckKind.CORRESPONDENT_BANK_COMPLIANCE,
        ).passed

    def test_passes_when_all_expected_bics_have_current_attestations(
        self,
        check_time: datetime,
    ) -> None:
        inputs = EligibilityInputs(
            check_time=check_time,
            requires_correspondent_compliance=True,
            expected_correspondent_bics=frozenset({"CITIUS33", "DEUTDEFF"}),
            correspondent_compliance=(
                _correspondent_current("CITIUS33", check_time),
                _correspondent_current("DEUTDEFF", check_time),
            ),
        )
        result = verify_eligibility(inputs)
        assert _check(
            result,
            EligibilityCheckKind.CORRESPONDENT_BANK_COMPLIANCE,
        ).passed

    def test_fails_when_expected_bic_missing(self, check_time: datetime) -> None:
        inputs = EligibilityInputs(
            check_time=check_time,
            requires_correspondent_compliance=True,
            expected_correspondent_bics=frozenset({"CITIUS33", "DEUTDEFF"}),
            correspondent_compliance=(_correspondent_current("CITIUS33", check_time),),
        )
        result = verify_eligibility(inputs)
        check = _check(result, EligibilityCheckKind.CORRESPONDENT_BANK_COMPLIANCE)
        assert not check.passed
        assert "missing" in (check.failure_reason or "")
        assert "DEUTDEFF" in (check.failure_reason or "")

    def test_fails_when_expected_bic_attestation_expired(
        self,
        check_time: datetime,
    ) -> None:
        inputs = EligibilityInputs(
            check_time=check_time,
            requires_correspondent_compliance=True,
            expected_correspondent_bics=frozenset({"CITIUS33"}),
            correspondent_compliance=(
                _correspondent_expired("CITIUS33", check_time),
            ),
        )
        result = verify_eligibility(inputs)
        check = _check(result, EligibilityCheckKind.CORRESPONDENT_BANK_COMPLIANCE)
        assert not check.passed
        assert "expired" in (check.failure_reason or "")
        assert "CITIUS33" in (check.failure_reason or "")


# ---------------------------------------------------------------------------
# Integration — full verification
# ---------------------------------------------------------------------------


class TestVerifyEligibilityIntegration:
    def test_all_five_checks_pass(
        self,
        check_time: datetime,
        kyc_current: KYCEvidence,
        kyb_current: KYBEvidence,
    ) -> None:
        inputs = EligibilityInputs(
            check_time=check_time,
            kyc=kyc_current,
            kyb=kyb_current,
            ofac_screenings=(_ofac_clear("bo-pension-fund-x", check_time),),
            sanctions_screenings=(_sanctions_clear("bo-pension-fund-x", check_time),),
            requires_correspondent_compliance=True,
            expected_correspondent_bics=frozenset({"CITIUS33"}),
            correspondent_compliance=(
                _correspondent_current("CITIUS33", check_time),
            ),
        )
        result = verify_eligibility(inputs)
        assert result.all_passed
        assert result.failed_checks == ()
        # Verify all five kinds are represented.
        kinds_present = {c.kind for c in result.checks}
        assert kinds_present == set(EligibilityCheckKind)

    def test_one_failure_isolates_correctly(
        self,
        check_time: datetime,
        kyc_current: KYCEvidence,
    ) -> None:
        # Fail OFAC only; everything else passes.
        inputs = EligibilityInputs(
            check_time=check_time,
            kyc=kyc_current,
            requires_kyb=False,
            ofac_screenings=(_ofac_match("cp-bad", check_time),),
            sanctions_screenings=(_sanctions_clear("bo-pension-fund-x", check_time),),
        )
        result = verify_eligibility(inputs)
        assert not result.all_passed
        failed_kinds = {c.kind for c in result.failed_checks}
        assert failed_kinds == {EligibilityCheckKind.OFAC}

    def test_all_five_failure_modes_represented(
        self,
        check_time: datetime,
    ) -> None:
        # KYC missing, KYB required and missing, OFAC not screened,
        # Sanctions not screened, Correspondent required and missing.
        inputs = EligibilityInputs(
            check_time=check_time,
            kyc=None,
            kyb=None,
            ofac_screenings=(),
            sanctions_screenings=(),
            requires_correspondent_compliance=True,
            expected_correspondent_bics=frozenset({"CITIUS33"}),
            correspondent_compliance=(),
        )
        result = verify_eligibility(inputs)
        failed_kinds = {c.kind for c in result.failed_checks}
        assert failed_kinds == set(EligibilityCheckKind)

    def test_pure_function_repeat_calls_match(
        self,
        check_time: datetime,
        kyc_current: KYCEvidence,
        kyb_current: KYBEvidence,
    ) -> None:
        """Per the deterministic discipline expected of agent-layer
        code: same inputs always produce the same verification."""
        inputs = EligibilityInputs(
            check_time=check_time,
            kyc=kyc_current,
            kyb=kyb_current,
            ofac_screenings=(_ofac_clear("bo-1", check_time),),
            sanctions_screenings=(_sanctions_clear("bo-1", check_time),),
        )
        first = verify_eligibility(inputs)
        second = verify_eligibility(inputs)
        assert first == second
