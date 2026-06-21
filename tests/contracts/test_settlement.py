"""Tests for ``aureon.contracts.settlement``.

Per AUR-CUSTODY-001 v1.0 Section V (Settlement Methods Taxonomy).
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from aureon.contracts.settlement import (
    AtomicSettlement,
    BilateralSettlement,
    CCPClearedSettlement,
    ConditionalSettlement,
    DvDSettlement,
    DvP1Settlement,
    DvP2Settlement,
    DvP3Settlement,
    FoPSettlement,
    PvPSettlement,
    SettlementMethod,
    SettlementMethodKind,
    TripartySettlement,
)

# A reusable TypeAdapter for the discriminated union — used to validate
# from raw dicts the way operations will when reconstructing from DSOR.
_ADAPTER: TypeAdapter[SettlementMethod] = TypeAdapter(SettlementMethod)


class TestKindEnumeration:
    """Per Section V the doctrine commits to eleven settlement methods."""

    def test_eleven_methods_enumerated(self) -> None:
        # Eleven canonical methods per AUR-CUSTODY-001 v1.0 Section V.
        assert len(SettlementMethodKind) == 11  # noqa: PLR2004

    @pytest.mark.parametrize(
        "value",
        [
            "DvP-1",
            "DvP-2",
            "DvP-3",
            "DvD",
            "PvP",
            "FoP",
            "atomic",
            "conditional",
            "triparty",
            "bilateral",
            "CCP-cleared",
        ],
    )
    def test_canonical_string_value_present(self, value: str) -> None:
        assert SettlementMethodKind(value).value == value


class TestSimpleMethodInstantiation:
    """Methods that carry no method-specific fields beyond ``kind``
    instantiate with no arguments (the discriminator defaults to the
    correct enum value)."""

    @pytest.mark.parametrize(
        ("model", "expected_kind"),
        [
            (DvP1Settlement, SettlementMethodKind.DVP_1),
            (DvP2Settlement, SettlementMethodKind.DVP_2),
            (DvP3Settlement, SettlementMethodKind.DVP_3),
            (DvDSettlement, SettlementMethodKind.DVD),
            (FoPSettlement, SettlementMethodKind.FOP),
            (BilateralSettlement, SettlementMethodKind.BILATERAL),
        ],
    )
    def test_instantiates_with_correct_discriminator(
        self,
        model: type,
        expected_kind: SettlementMethodKind,
    ) -> None:
        instance = model()
        assert instance.kind is expected_kind


class TestPvPSettlement:
    def test_default_via_cls_is_false(self) -> None:
        pvp = PvPSettlement()
        assert pvp.via_cls is False

    def test_via_cls_can_be_set(self) -> None:
        pvp = PvPSettlement(via_cls=True)
        assert pvp.via_cls is True


class TestAtomicSettlement:
    def test_requires_rail(self) -> None:
        with pytest.raises(ValidationError):
            AtomicSettlement()  # type: ignore[call-arg]

    def test_empty_rail_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AtomicSettlement(rail="")

    @pytest.mark.parametrize(
        "rail", ["ethereum_l1", "base", "arbitrum", "solana", "fed_l1"]
    )
    def test_known_rails_accepted(self, rail: str) -> None:
        atomic = AtomicSettlement(rail=rail)
        assert atomic.rail == rail


class TestConditionalSettlement:
    def test_requires_condition(self) -> None:
        with pytest.raises(ValidationError):
            ConditionalSettlement()  # type: ignore[call-arg]

    def test_empty_condition_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConditionalSettlement(condition="")


class TestTripartySettlement:
    def test_requires_agent(self) -> None:
        with pytest.raises(ValidationError):
            TripartySettlement()  # type: ignore[call-arg]

    def test_empty_agent_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TripartySettlement(agent="")

    def test_named_agent_accepted(self) -> None:
        triparty = TripartySettlement(agent="BNY_MELLON_TRIPARTY")
        assert triparty.agent == "BNY_MELLON_TRIPARTY"


class TestCCPClearedSettlement:
    def test_requires_ccp(self) -> None:
        with pytest.raises(ValidationError):
            CCPClearedSettlement()  # type: ignore[call-arg]

    def test_empty_ccp_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CCPClearedSettlement(ccp="")

    def test_named_ccp_accepted(self) -> None:
        ccp = CCPClearedSettlement(ccp="FICC_GSD")
        assert ccp.ccp == "FICC_GSD"


class TestImmutability:
    """All settlement-method models are frozen — settlement decisions on
    a stamped operation must not mutate after the fact (consistent with
    AUR-CANONICAL-001 v1.6 Thifur-R guardrail "immutable lineage —
    stamped at execution, never modified post-execution")."""

    def test_dvp1_is_frozen(self) -> None:
        dvp1 = DvP1Settlement()
        with pytest.raises(ValidationError):
            dvp1.kind = SettlementMethodKind.DVP_2  # type: ignore[misc,assignment]

    def test_atomic_is_frozen(self) -> None:
        atomic = AtomicSettlement(rail="base")
        with pytest.raises(ValidationError):
            atomic.rail = "solana"  # type: ignore[misc]


class TestDiscriminatedUnion:
    """The discriminated union dispatches on the ``kind`` field. This
    is how operations validate a settlement method coming from a raw
    dict (e.g., reconstructing from a DSOR record)."""

    def test_dvp1_from_dict(self) -> None:
        method = _ADAPTER.validate_python({"kind": "DvP-1"})
        assert isinstance(method, DvP1Settlement)

    def test_atomic_from_dict_with_rail(self) -> None:
        method = _ADAPTER.validate_python({"kind": "atomic", "rail": "base"})
        assert isinstance(method, AtomicSettlement)
        assert method.rail == "base"

    def test_triparty_from_dict_with_agent(self) -> None:
        method = _ADAPTER.validate_python(
            {"kind": "triparty", "agent": "JPM_COLLATERAL_MGMT"}
        )
        assert isinstance(method, TripartySettlement)
        assert method.agent == "JPM_COLLATERAL_MGMT"

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python({"kind": "fictional-method"})

    def test_atomic_without_rail_rejected_via_union(self) -> None:
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python({"kind": "atomic"})

    def test_triparty_without_agent_rejected_via_union(self) -> None:
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python({"kind": "triparty"})

    def test_conditional_without_condition_rejected_via_union(self) -> None:
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python({"kind": "conditional"})

    def test_ccp_without_ccp_id_rejected_via_union(self) -> None:
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python({"kind": "CCP-cleared"})

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {"kind": "DvP-1", "spurious_field": "value"}
            )
