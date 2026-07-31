"""Tests for the ISO 20022 emit path — AUR-CUSTODY-CASH-001 §VIII.

The load-bearing tests here validate emitted messages against the **real
ISO 20022 XSDs** in `tests/fixtures/iso20022/`, not against hand-written
assertions. That distinction is the whole point: the first run of this
emitter produced `+0000` for `xs:dateTime` (which requires `+00:00`) and
silently stripped monetary scale. Both passed every assertion a human would
have thought to write. Only the schema caught them.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from lxml import etree

from atreides.messaging import (
    BASE_ISO_20022,
    CashLegInstruction,
    DepositoryProfile,
    FinancialInstitution,
    SettlementMethod,
    emit_business_application_header,
    emit_fi_credit_transfer,
    emit_instruction_artifact,
    settlement_method_for_rail,
)
from atreides.messaging.profile import DTCC_SETTLEMENT_PENDING, FEDWIRE_PENDING
from atreides.rails.cato_f import CashRail

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "iso20022"
T0 = datetime(2026, 7, 31, 15, 0, tzinfo=UTC)


def _schema(name: str) -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(str(FIXTURES / f"{name}.xsd")))


def _instr(**kw) -> CashLegInstruction:
    base = {
        "message_id": "AUR20260731000001",
        "end_to_end_id": "E2E-0001",
        "created_at": T0,
        "amount": Decimal("1000000.00"),
        "currency": "USD",
        "debtor": FinancialInstitution("CHASUS33"),
        "creditor": FinancialInstitution("BOFAUS3N"),
        "settlement_method": SettlementMethod.CLEARING_SYSTEM,
        "sender": FinancialInstitution("CHASUS33"),
        "receiver": FinancialInstitution("DTCYUS33"),
    }
    base.update(kw)
    return CashLegInstruction(**base)  # type: ignore[arg-type]


# --- the tests that actually matter: real schema conformance ---------------


class TestSchemaConformance:
    def test_pacs_009_validates_against_the_published_xsd(self) -> None:
        doc = etree.fromstring(emit_fi_credit_transfer(_instr()))
        schema = _schema("pacs.009.001.13")
        assert schema.validate(doc), str(schema.error_log)

    def test_business_application_header_validates(self) -> None:
        hdr = etree.fromstring(emit_business_application_header(_instr()))
        schema = _schema("head.001.001.04")
        assert schema.validate(hdr), str(schema.error_log)

    @pytest.mark.parametrize("method", list(SettlementMethod))
    def test_every_settlement_method_yields_a_valid_message(
        self, method: SettlementMethod
    ) -> None:
        doc = etree.fromstring(emit_fi_credit_transfer(_instr(settlement_method=method)))
        schema = _schema("pacs.009.001.13")
        assert schema.validate(doc), str(schema.error_log)

    def test_optional_creditor_name_still_validates(self) -> None:
        doc = etree.fromstring(
            emit_fi_credit_transfer(
                _instr(creditor=FinancialInstitution("BOFAUS3N", "Bank of America"))
            )
        )
        schema = _schema("pacs.009.001.13")
        assert schema.validate(doc), str(schema.error_log)


# --- regressions the schema found, which assertions would not -------------


class TestSchemaCaughtRegressions:
    def test_datetime_uses_colon_offset_not_plus_0000(self) -> None:
        """strftime('%z') emits +0000; xs:dateTime requires +00:00 or Z."""
        xml = emit_fi_credit_transfer(_instr()).decode()
        assert "+00:00" in xml
        assert "+0000<" not in xml

    def test_non_utc_offset_is_rendered_with_a_colon(self) -> None:
        est = timezone(timedelta(hours=-5))
        doc = etree.fromstring(
            emit_fi_credit_transfer(_instr(created_at=T0.astimezone(est)))
        )
        schema = _schema("pacs.009.001.13")
        assert schema.validate(doc), str(schema.error_log)

    def test_monetary_scale_is_preserved(self) -> None:
        """normalize() turns 1000000.00 into 1E+6, losing cents."""
        xml = emit_fi_credit_transfer(_instr()).decode()
        assert "<IntrBkSttlmAmt Ccy=\"USD\">1000000.00</IntrBkSttlmAmt>" in xml

    def test_large_round_amount_is_not_scientific_notation(self) -> None:
        xml = emit_fi_credit_transfer(_instr(amount=Decimal("1E+6"))).decode()
        assert "1000000" in xml and "E+" not in xml
        assert _schema("pacs.009.001.13").validate(etree.fromstring(xml.encode()))


# --- the domain model refuses what the schema would permit ----------------


class TestDomainStricterThanSchema:
    def test_bicfi_pattern_enforced(self) -> None:
        with pytest.raises(ValueError, match="invalid BICFI"):
            FinancialInstitution("NOTABIC")

    def test_bicfi_accepts_both_8_and_11_character_forms(self) -> None:
        assert FinancialInstitution("CHASUS33").bicfi == "CHASUS33"
        assert FinancialInstitution("CHASUS33XXX").bicfi == "CHASUS33XXX"

    def test_message_id_bounded_to_max35text(self) -> None:
        with pytest.raises(ValueError, match="Max35Text"):
            _instr(message_id="X" * 36)

    def test_naive_datetime_rejected(self) -> None:
        """A naive timestamp silently asserts the emitter's local zone."""
        with pytest.raises(ValueError, match="timezone-aware"):
            _instr(created_at=datetime(2026, 7, 31, 15, 0))

    def test_non_positive_amount_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            _instr(amount=Decimal("0"))

    def test_currency_must_be_three_letters(self) -> None:
        with pytest.raises(ValueError, match="ActiveCurrencyCode"):
            _instr(currency="US")


# --- the join between CATO-F and the wire ---------------------------------


class TestRailToSettlementMethod:
    @pytest.mark.parametrize(
        ("rail", "expected"),
        [
            (CashRail.FEDWIRE, SettlementMethod.CLEARING_SYSTEM),
            (CashRail.FEDNOW, SettlementMethod.CLEARING_SYSTEM),
            (CashRail.CHIPS, SettlementMethod.CLEARING_SYSTEM),
            (CashRail.NSS_DTC_NSCC, SettlementMethod.CLEARING_SYSTEM),
            (CashRail.FICC_GSD_FUNDS_ONLY, SettlementMethod.CLEARING_SYSTEM),
            (CashRail.CORRESPONDENT, SettlementMethod.COVER),
        ],
    )
    def test_gate_selected_rail_maps_to_a_settlement_method(
        self, rail: CashRail, expected: SettlementMethod
    ) -> None:
        assert settlement_method_for_rail(rail) is expected

    @pytest.mark.parametrize(
        "rail",
        [
            CashRail.TOKENIZED_DEPOSIT,
            CashRail.REGULATED_STABLECOIN,
            CashRail.PORTS_WHOLESALE,
        ],
    )
    def test_non_pacs_rails_raise_rather_than_defaulting(
        self, rail: CashRail
    ) -> None:
        """Defaulting these to CLRG would assert a clearing-system
        settlement that never happens."""
        with pytest.raises(ValueError, match="no ISO 20022 credit-transfer"):
            settlement_method_for_rail(rail)


# --- the cardinal boundary, and the profile seam --------------------------


class TestBoundaryAndProfile:
    def test_artifact_can_never_be_a_submission(self) -> None:
        art = emit_instruction_artifact(_instr())
        assert art.is_submission is False
        with pytest.raises(Exception):
            art.is_submission = True  # type: ignore[misc]

    def test_artifact_carries_lineage_and_profile_provenance(self) -> None:
        art = emit_instruction_artifact(_instr(dsor_lineage_uri="dsor://op/1"))
        assert art.dsor_lineage_uri == "dsor://op/1"
        assert art.message_definition == "pacs.009.001.13"
        assert art.profile_name == "base-iso20022"
        assert art.profile_verified is True

    def test_variant_selection_is_profile_data_not_code(self) -> None:
        """Switching variant must change the namespace without a code change."""
        alt = DepositoryProfile(name="alt", fi_credit_transfer="pacs.009.001.08")
        xml = emit_fi_credit_transfer(_instr(), alt).decode()
        assert "pacs.009.001.08" in xml

    def test_unverified_profiles_are_flagged_not_silently_trusted(self) -> None:
        for profile in (DTCC_SETTLEMENT_PENDING, FEDWIRE_PENDING):
            assert profile.is_base_standard
            assert not profile.verified_against_published_spec
            assert "UNVERIFIED" in profile.name

    def test_base_standard_profile_is_verified(self) -> None:
        assert BASE_ISO_20022.verified_against_published_spec
        assert not BASE_ISO_20022.is_base_standard

    def test_business_service_omitted_when_profile_does_not_set_it(self) -> None:
        """Emitting optional fields a venue does not expect is how a valid
        message gets rejected."""
        assert b"BizSvc" not in emit_business_application_header(_instr())
        with_svc = DepositoryProfile(name="v", business_service="swift.cbprplus.02")
        assert b"BizSvc" in emit_business_application_header(_instr(), with_svc)


def test_emit_is_deterministic() -> None:
    a = emit_instruction_artifact(_instr())
    b = emit_instruction_artifact(_instr())
    assert a.document_xml == b.document_xml
    assert a.header_xml == b.header_xml


def test_institution_name_bounded_to_max140text() -> None:
    with pytest.raises(ValueError, match="Max140Text"):
        FinancialInstitution("CHASUS33", "X" * 141)
