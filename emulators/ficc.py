"""Independent, non-submitting synthetic FICC/ISO inbound emitter."""

from datetime import datetime
from decimal import Decimal

from cannae_kernel.provenance import Provenance

from atreides.closed_trade import InboundStatus, InboundStreetFact, TreasuryDvpInstruction


def emit_inbound(
    instruction: TreasuryDvpInstruction,
    *,
    status: InboundStatus = InboundStatus.SETTLED,
    amount_delta: Decimal = Decimal(0),
    quantity_delta: Decimal = Decimal(0),
    late: bool = False,
) -> InboundStreetFact:
    amount = instruction.cash_amount + amount_delta
    quantity = instruction.quantity + quantity_delta
    pacs = (
        '<FIToFIPmtStsRpt xmlns="urn:iso:std:iso:20022:tech:xsd:pacs.002.001.12">'
        f"<TxInfAndSts><OrgnlEndToEndId>{instruction.trade_id}</OrgnlEndToEndId>"
        f"<TxSts>{status.value}</TxSts></TxInfAndSts></FIToFIPmtStsRpt>"
    ).encode()
    camt = (
        '<BkToCstmrDbtCdtNtfctn xmlns="urn:iso:std:iso:20022:tech:xsd:camt.054.001.12">'
        f'<Ntry><Amt Ccy="{instruction.currency}">{amount}</Amt></Ntry>'
        "</BkToCstmrDbtCdtNtfctn>"
    ).encode()
    ficc = (
        "trade_id,status,cusip,quantity,amount\n"
        f"{instruction.trade_id},{status.value},{instruction.cusip},{quantity},{amount}\n"
    ).encode()
    return InboundStreetFact(
        trade_id=instruction.trade_id,
        status=status,
        ccp_obligation_amount=amount,
        cash_movement_amount=amount,
        securities_movement_quantity=quantity,
        observed_at=datetime.fromisoformat("2026-10-23T14:00:00+00:00"),
        provenance=Provenance.FACT_SYNTHETIC,
        pacs002=pacs,
        camt054=camt,
        ficc_status=ficc,
        late=late,
    )
