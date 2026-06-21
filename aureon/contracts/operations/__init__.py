"""Custody operation models — typed substrate for every custody operation.

Per AUR-CUSTODY-001 v1.0 Section V (Transaction Types and Settlement
Methods).

The base ``CustodyOperation`` lives in ``aureon.contracts.operations.base``
and carries the four architectural cross-validators (UR-F requires
inherent-safety surface; inherent-safety surface requires quorum
authority routing; inherent-safety operations require authority tier
QUORUM; quorum-authority field consistency with the lineage tier).

Each per-asset-class module contributes one operation model with a
distinct ``kind`` discriminator. The package-level ``CustodyOperationUnion``
TypeAdapter is the entry point downstream agents and DSOR replay use to
deserialise an operation from a raw dict.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from aureon.contracts.operations.base import CustodyOperation
from aureon.contracts.operations.derivatives import (
    DerivativeOperation,
    DerivativeTransactionType,
)
from aureon.contracts.operations.digital import (
    NativeDigitalOperation,
    NativeDigitalTransactionType,
)
from aureon.contracts.operations.equity import (
    EquityOperation,
    EquityTransactionType,
)
from aureon.contracts.operations.fixed_income import (
    FixedIncomeOperation,
    FixedIncomeTransactionType,
)
from aureon.contracts.operations.funds import (
    FundOperation,
    FundTransactionType,
)
from aureon.contracts.operations.fx import FXOperation, FXTransactionType
from aureon.contracts.operations.lifecycle import (
    LifecycleEventType,
    LifecycleOperation,
)
from aureon.contracts.operations.structured import (
    StructuredOperation,
    StructuredTransactionType,
)
from aureon.contracts.operations.tokenized import (
    TokenizedOperation,
    TokenizedTransactionType,
)

CustodyOperationUnion = Annotated[
    EquityOperation
    | FixedIncomeOperation
    | FXOperation
    | DerivativeOperation
    | FundOperation
    | StructuredOperation
    | TokenizedOperation
    | NativeDigitalOperation
    | LifecycleOperation,
    Field(discriminator="kind"),
]
"""Discriminated union over every per-asset-class operation model. The
``kind`` field is the discriminator — `equity`, `fixed_income`, `fx`,
`derivative`, `fund`, `structured`, `tokenized`, `native_digital`,
`lifecycle`. Subsequent doctrine work (per-asset-class operational
specifications for physical commodities, real estate, IP, insurance,
etc.) extends this union as new operation modules are added."""


__all__ = [
    "CustodyOperation",
    "CustodyOperationUnion",
    "DerivativeOperation",
    "DerivativeTransactionType",
    "EquityOperation",
    "EquityTransactionType",
    "FXOperation",
    "FXTransactionType",
    "FixedIncomeOperation",
    "FixedIncomeTransactionType",
    "FundOperation",
    "FundTransactionType",
    "LifecycleEventType",
    "LifecycleOperation",
    "NativeDigitalOperation",
    "NativeDigitalTransactionType",
    "StructuredOperation",
    "StructuredTransactionType",
    "TokenizedOperation",
    "TokenizedTransactionType",
]
