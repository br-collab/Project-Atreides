"""Tests for ``aureon.contracts.operations.fixed_income``.

Per AUR-CUSTODY-001 v1.0 Section V Fixed Income.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aureon.contracts.custody_object import OrdinarySafekeepingObject
from aureon.contracts.dsor_stub import DSORLineageStub
from aureon.contracts.failure_mode import FailureModeClass
from aureon.contracts.operations.fixed_income import (
    FixedIncomeOperation,
    FixedIncomeTransactionType,
)
from aureon.contracts.settlement import (
    DvP1Settlement,
    TripartySettlement,
)


class TestFixedIncomeTransactionTypeCoverage:
    @pytest.mark.parametrize(
        "txn_type",
        [
            FixedIncomeTransactionType.OUTRIGHT_PURCHASE,
            FixedIncomeTransactionType.OUTRIGHT_SALE,
            FixedIncomeTransactionType.WHEN_ISSUED,
            FixedIncomeTransactionType.REPO_OVERNIGHT,
            FixedIncomeTransactionType.REPO_TERM,
            FixedIncomeTransactionType.REPO_TRIPARTY,
            FixedIncomeTransactionType.REPO_BILATERAL,
            FixedIncomeTransactionType.REVERSE_REPO,
            FixedIncomeTransactionType.BUY_SELL_BACK,
            FixedIncomeTransactionType.COUPON_STRIP,
            FixedIncomeTransactionType.COUPON_RECONSTITUTE,
            FixedIncomeTransactionType.MBS_TBA,
            FixedIncomeTransactionType.MBS_FACTOR_ADJUSTMENT,
        ],
    )
    def test_doctrinal_types_present(
        self, txn_type: FixedIncomeTransactionType
    ) -> None:
        assert txn_type in FixedIncomeTransactionType


class TestFixedIncomeConstruction:
    def test_outright_purchase(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = FixedIncomeOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RA,
            transaction_type=FixedIncomeTransactionType.OUTRIGHT_PURCHASE,
            settlement_method=DvP1Settlement(),
        )
        assert op.kind == "fixed_income"

    def test_repo_overnight_no_term_required(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = FixedIncomeOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RA,
            transaction_type=FixedIncomeTransactionType.REPO_OVERNIGHT,
            settlement_method=TripartySettlement(
                agent="BNY_MELLON_TRIPARTY"
            ),
        )
        assert op.repo_term_days is None


class TestRepoTermRule:
    def test_repo_term_without_days_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(
            ValidationError, match=r"repo_term_days"
        ):
            FixedIncomeOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RA,
                transaction_type=FixedIncomeTransactionType.REPO_TERM,
            )

    def test_repo_term_with_days_accepted(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        op = FixedIncomeOperation(
            lineage=lineage_t1,
            custody_object=ordinary_treasury,
            failure_mode_class=FailureModeClass.RA,
            transaction_type=FixedIncomeTransactionType.REPO_TERM,
            repo_term_days=14,
        )
        assert op.repo_term_days == 14  # noqa: PLR2004

    def test_zero_term_days_rejected(
        self,
        lineage_t1: DSORLineageStub,
        ordinary_treasury: OrdinarySafekeepingObject,
    ) -> None:
        with pytest.raises(ValidationError):
            FixedIncomeOperation(
                lineage=lineage_t1,
                custody_object=ordinary_treasury,
                failure_mode_class=FailureModeClass.RA,
                transaction_type=FixedIncomeTransactionType.REPO_TERM,
                repo_term_days=0,
            )
