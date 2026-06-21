"""Tests for ``aureon.contracts.failure_mode``.

Per AUR-CUSTODY-001 v1.0 Section VIII (four-class custody taxonomy).
"""

from __future__ import annotations

import pytest

from aureon.contracts.failure_mode import FailureModeClass


class TestFailureModeClassMembership:
    """The taxonomy is exactly four classes — no more, no less."""

    def test_taxonomy_has_exactly_four_classes(self) -> None:
        # Doctrinally fixed at four per AUR-CUSTODY-001 v1.0 Section VIII.
        assert len(FailureModeClass) == 4  # noqa: PLR2004

    def test_ra_is_recoverable_automatic(self) -> None:
        assert FailureModeClass.RA.value == "RA"

    def test_rm_is_recoverable_manual(self) -> None:
        assert FailureModeClass.RM.value == "RM"

    def test_ur_r_is_recoverable_via_other_means(self) -> None:
        assert FailureModeClass.UR_R.value == "UR-R"

    def test_ur_f_is_unrecoverable_final(self) -> None:
        assert FailureModeClass.UR_F.value == "UR-F"


class TestIsUnrecoverable:
    """``is_unrecoverable`` is true for UR-R and UR-F only.

    Per AUR-CANONICAL-001 v1.6 Axiom 10, unrecoverable failures must not
    be reachable on inherent-safety surfaces. The property is what
    operation-level validators consult.
    """

    def test_ra_is_not_unrecoverable(self) -> None:
        assert FailureModeClass.RA.is_unrecoverable is False

    def test_rm_is_not_unrecoverable(self) -> None:
        assert FailureModeClass.RM.is_unrecoverable is False

    def test_ur_r_is_unrecoverable(self) -> None:
        assert FailureModeClass.UR_R.is_unrecoverable is True

    def test_ur_f_is_unrecoverable(self) -> None:
        assert FailureModeClass.UR_F.is_unrecoverable is True


class TestIsFinal:
    """``is_final`` is true for UR-F only.

    Per AUR-CUSTODY-001 v1.0 Section VIII, UR-F operations specifically
    demand inherent-safety placement with quorum authority. UR-R has
    bounded economic exposure through external recovery and does not by
    itself force inherent-safety placement.
    """

    def test_ra_is_not_final(self) -> None:
        assert FailureModeClass.RA.is_final is False

    def test_rm_is_not_final(self) -> None:
        assert FailureModeClass.RM.is_final is False

    def test_ur_r_is_not_final(self) -> None:
        assert FailureModeClass.UR_R.is_final is False

    def test_ur_f_is_final(self) -> None:
        assert FailureModeClass.UR_F.is_final is True


class TestSerializationStability:
    """The string values are part of the contract surface — they appear
    in DSOR records and external regulatory artifacts. Changes to the
    string values are doctrine-modifying changes."""

    @pytest.mark.parametrize(
        ("member", "expected"),
        [
            (FailureModeClass.RA, "RA"),
            (FailureModeClass.RM, "RM"),
            (FailureModeClass.UR_R, "UR-R"),
            (FailureModeClass.UR_F, "UR-F"),
        ],
    )
    def test_string_value_is_canonical(
        self, member: FailureModeClass, expected: str
    ) -> None:
        assert member.value == expected

    def test_round_trip_through_string(self) -> None:
        for member in FailureModeClass:
            assert FailureModeClass(member.value) is member
