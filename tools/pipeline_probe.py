"""End-to-end pipeline probe - run a scenario, get a trace.

The four builds landed as islands. Each has its own tests and none of them
had ever run against the others, which means the seams between them were
untested by construction. This runs a named scenario from funding through
the gate, the emitted artifact, the readback and the break surface, and
prints what every stage decided.

It is a probe, not a test suite. It does not assert that the output is
correct; it shows you what the output *is*, so a human can look at it and
say whether it should be that. `--json` makes runs diffable, which is what
makes it usable for a controlled test over days rather than minutes.

The one thing it does assert is **determinism**: every scenario runs twice
and the two traces are compared byte for byte. A framework whose whole claim
is replayability should notice the day that stops being true, and it should
notice on the first run after the change rather than on the day somebody
asks for a decision from three months ago.

Usage::

    python3 tools/pipeline_probe.py                  # every scenario
    python3 tools/pipeline_probe.py --list
    python3 tools/pipeline_probe.py silence queued
    python3 tools/pipeline_probe.py --json > run-01.json
    diff <(... run-01.json) <(... run-02.json)

Exit codes: 0 all scenarios ran and were deterministic; 1 a determinism
check failed; 2 a scenario raised.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import UTC, datetime
from decimal import Decimal

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from atreides.contracts.margin_impact import (  # noqa: E402
    absent_margin_assessment,
    margin_impact_for_clearing_fund_deficiency,
    margin_priority_rank,
)
from atreides.messaging.canonical import (  # noqa: E402
    CashLegInstruction,
    FinancialInstitution,
    SettlementMethod,
)
from atreides.messaging.emit import emit_instruction_artifact  # noqa: E402
from atreides.messaging.readback import (  # noqa: E402
    SettlementStatus,
    absent_readback,
    ingest_readback,
)
from atreides.rails.cato_f import (  # noqa: E402
    CashRail,
    OperationContext,
    RailState,
    RailStatus,
    evaluate,
)
from atreides.rails.cns import (  # noqa: E402
    CloseOutRegime,
    MarketProfile,
    net_positions,
    settle_net_position,
)
from atreides.rails.determination import (  # noqa: E402
    DeterminationOutcome,
    DeterminationProfile,
    RevocationForm,
    absent_determination_profile,
    classify_determination,
    obligation_finality_class,
)
from atreides.rails.finality import FinalityClass  # noqa: E402
from atreides.rails.funding_state import (  # noqa: E402
    CashFlow,
    FundingInputs,
    project_funding,
)

D = Decimal

#: Rationale strings are long by design; the human view clips them and the
#: JSON view does not.
_TRUNCATE_AT = 150

#: Fixed so that a trace is comparable across runs and across machines. The
#: models consult no clock; this is the caller supplying one, which is the
#: contract every pure module in this framework expects.
FIXED_DTG = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

_ALICE = FinancialInstitution(bicfi="AAAAUS33XXX", name="Alice Bank")
_BOB = FinancialInstitution(bicfi="BBBBUS33XXX", name="Bob Bank")


def _rails() -> dict[CashRail, RailState]:
    return {
        CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200),
        CashRail.CHIPS: RailState(CashRail.CHIPS, RailStatus.AVAILABLE, 7200),
        CashRail.PORTS_WHOLESALE: RailState(
            CashRail.PORTS_WHOLESALE, RailStatus.NOT_YET_ISSUED
        ),
    }


def _instruction(e2e: str = "E2E-0001", msg: str = "MSG-0001") -> CashLegInstruction:
    return CashLegInstruction(
        message_id=msg,
        end_to_end_id=e2e,
        created_at=FIXED_DTG,
        amount=D("1000000.00"),
        currency="USD",
        debtor=_ALICE,
        creditor=_BOB,
        settlement_method=SettlementMethod.CLEARING_SYSTEM,
        sender=_ALICE,
        receiver=_BOB,
    )


def _pacs002(entries: str, original_message_id: str | None = "MSG-0001") -> bytes:
    ns = "urn:iso:std:iso:20022:tech:xsd:pacs.002.001.16"
    grp = ""
    if original_message_id is not None:
        grp = (
            "<OrgnlGrpInfAndSts>"
            f"<OrgnlMsgId>{original_message_id}</OrgnlMsgId>"
            "<OrgnlMsgNmId>pacs.009.001.13</OrgnlMsgNmId>"
            "</OrgnlGrpInfAndSts>"
        )
    return (
        f'<Document xmlns="{ns}"><FIToFIPmtStsRpt>'
        "<GrpHdr><MsgId>STS-0001</MsgId>"
        "<CreDtTm>2026-08-14T13:00:00Z</CreDtTm></GrpHdr>"
        f"{grp}{entries}</FIToFIPmtStsRpt></Document>"
    ).encode()


def _tx(e2e: str | None, status: str | None) -> str:
    parts = ["<TxInfAndSts>"]
    if e2e is not None:
        parts.append(f"<OrgnlEndToEndId>{e2e}</OrgnlEndToEndId>")
    parts.append("<OrgnlTxId>TX-1</OrgnlTxId>")
    if status is not None:
        parts.append(f"<TxSts>{status}</TxSts>")
    parts.append("</TxInfAndSts>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def _cash_leg(
    trace: dict[str, object],
    *,
    opening: Decimal,
    obligation: Decimal,
    flows: tuple[CashFlow, ...] = (),
    determination_outcome=None,
    clearing_fund_posted: Decimal | None = None,
    clearing_fund_requirement: Decimal | None = None,
) -> None:
    outcome = determination_outcome or DeterminationOutcome.NOT_APPLICABLE
    posted = clearing_fund_posted if clearing_fund_posted is not None else D("500000")
    requirement = (
        clearing_fund_requirement if clearing_fund_requirement is not None else D("500000")
    )

    funding_inputs = FundingInputs(
        opening_position=opening,
        obligation=obligation,
        finality_class=FinalityClass.GROSS_FINAL,
        settlement_offset_seconds=3600,
        window_close_offset_seconds=14400,
        flows=flows,
        net_debit_cap=D("50000000"),
        clearing_fund_requirement=requirement,
        clearing_fund_posted=posted,
        determination_outcome=outcome,
    )
    projection = project_funding(funding_inputs)
    trace["funding"] = {
        "disposition": projection.disposition.value,
        "settles": projection.settles,
        "qualified": projection.qualified,
        "is_failure": projection.is_failure,
        "shortfall": str(projection.shortfall),
        "funded_at_offset_seconds": projection.funded_at_offset_seconds,
        "rationale": projection.rationale,
    }

    operation = OperationContext(
        notional=obligation,
        currency="USD",
        is_material=False,
        is_lvps_material=False,
        determination_outcome=outcome,
    )
    decision = evaluate(
        operation=operation,
        funding=projection.to_gate_input(),
        rails=_rails(),
        ofr_stlfsi4=0.0,
    )
    trace["gate"] = {
        "decision": decision.decision.value,
        "reason_code": decision.reason_code.value,
        "recommended_rail": decision.recommended_rail.value
        if decision.recommended_rail
        else None,
        "rail_finality_class": decision.finality_class.value
        if decision.finality_class
        else None,
        "obligation_finality_class": decision.obligation_finality_class.value
        if decision.obligation_finality_class
        else None,
        "rationale": decision.rationale,
    }

    if decision.proceeds:
        artifact = emit_instruction_artifact(_instruction())
        trace["artifact"] = {
            "message_definition": artifact.message_definition,
            "profile_name": artifact.profile_name,
            "profile_verified": artifact.profile_verified,
            "is_submission": artifact.is_submission,
            "document_bytes": len(artifact.document_xml),
            "header_bytes": len(artifact.header_xml),
        }
    else:
        trace["artifact"] = None


def _readback(trace: dict[str, object], match) -> None:
    trace["readback"] = {
        "is_absent": match.is_absent,
        "clean": match.clean,
        "entry_count": match.report.entry_count,
        "parsed_entries": len(match.report.entries),
        "malformed_entries": len(match.report.malformed),
        "matched": {k: v.value for k, v in sorted(match.matched.items())},
        "settled_ids": list(match.settled_ids),
        "breaks": [
            {"code": b.code.value, "end_to_end_id": b.end_to_end_id, "detail": b.detail}
            for b in match.breaks
        ],
    }


def _margin(trace: dict[str, object], impact) -> None:
    trace["margin"] = {
        "disposition": impact.disposition.value,
        "direction": impact.direction.value,
        "observability": impact.observability.value,
        "delta_amount": str(impact.delta_amount) if impact.delta_amount else None,
        "escalates": impact.escalates,
        "priority_rank": margin_priority_rank(impact),
        "basis": impact.basis,
    }


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def scenario_clean_cash() -> dict[str, object]:
    """Funded, gate clears, artifact emitted, venue confirms settlement."""
    trace: dict[str, object] = {}
    _cash_leg(trace, opening=D("10000000"), obligation=D("1000000"))
    _readback(
        trace,
        ingest_readback(_pacs002(_tx("E2E-0001", "ACSC")), (_instruction(),)),
    )
    _margin(trace, absent_margin_assessment("no margined position touched"))
    return trace


def scenario_queued() -> dict[str, object]:
    """Short at the settlement instant on a gross-final rail.

    The disposition to look at is WILL_QUEUE rather than WILL_FAIL, and the
    gate holding anyway. Both are correct and they are correct for different
    reasons: the instruction will settle if left alone, and it should not be
    released now.
    """
    trace: dict[str, object] = {}
    _cash_leg(
        trace,
        opening=D("0"),
        obligation=D("1000000"),
        flows=(CashFlow(7200, D("1000000"), "inbound receipt"),),
    )
    _readback(trace, absent_readback("instruction not released; nothing submitted"))
    _margin(trace, absent_margin_assessment("funding hold, margin not assessed"))
    return trace


def scenario_silence() -> dict[str, object]:
    """Instruction released, nothing came back.

    The scenario the whole readback module exists for. Nothing is
    established: not settlement, not rejection.
    """
    trace: dict[str, object] = {}
    _cash_leg(trace, opening=D("10000000"), obligation=D("1000000"))
    _readback(trace, absent_readback("venue file not yet retrieved by the operator"))
    _margin(trace, absent_margin_assessment("no readback, margin state unknown"))
    return trace


def scenario_unsolicited() -> dict[str, object]:
    """A status for an instruction this framework never prepared.

    Either a venue misroute or a payment that left the firm outside the
    governed path.
    """
    trace: dict[str, object] = {}
    _cash_leg(trace, opening=D("10000000"), obligation=D("1000000"))
    _readback(
        trace,
        ingest_readback(
            _pacs002(_tx("E2E-GHOST", "ACSC"), original_message_id=None),
            (_instruction(),),
        ),
    )
    _margin(trace, absent_margin_assessment("unsolicited status, nothing to assess"))
    return trace


def scenario_partial_batch() -> dict[str, object]:
    """A venue file with one unreadable record among three.

    The other two must still reconcile, and the bad one must still surface.
    """
    trace: dict[str, object] = {}
    _cash_leg(trace, opening=D("10000000"), obligation=D("1000000"))
    entries = _tx("E2E-0001", "ACSC") + _tx("E2E-BAD", None) + _tx("E2E-0002", "RJCT")
    _readback(
        trace,
        ingest_readback(
            _pacs002(entries, original_message_id=None),
            (_instruction(), _instruction("E2E-0002", "MSG-0002")),
        ),
    )
    _margin(trace, absent_margin_assessment("mixed outcome, margin not assessed"))
    return trace


def scenario_regression() -> dict[str, object]:
    """A settlement the record shows as complete, reported as rejected."""
    trace: dict[str, object] = {}
    _cash_leg(trace, opening=D("10000000"), obligation=D("1000000"))
    _readback(
        trace,
        ingest_readback(
            _pacs002(_tx("E2E-0001", "RJCT")),
            (_instruction(),),
            {"E2E-0001": SettlementStatus.SETTLED},
        ),
    )
    _margin(trace, absent_margin_assessment("regression under investigation"))
    return trace


def scenario_contingent_qualified() -> dict[str, object]:
    """A contingent payout on a venue that may cancel and return funds.

    Two finality classes on one decision: the money is final on its rail and
    the entitlement is not.
    """
    trace: dict[str, object] = {}
    profile = DeterminationProfile(
        venue_id="VENUE-EC",
        revocation_form=RevocationForm.CANCELLATION_AND_RETURN_OF_FUNDS,
        provenance="Venue rulebook, emergency authority provision",
    )
    outcome = classify_determination(
        profile=profile, instrument_is_contingent=True, determined=True
    )
    trace["determination"] = {
        "outcome": outcome.value,
        "obligation_finality_class": (
            obligation_finality_class(outcome).value
            if obligation_finality_class(outcome)
            else None
        ),
        "revocation_form": profile.revocation_form.value,
        "qualification_window_seconds": profile.qualification_window_seconds,
    }
    _cash_leg(
        trace,
        opening=D("10000000"),
        obligation=D("1000000"),
        determination_outcome=outcome,
    )
    _readback(
        trace,
        ingest_readback(_pacs002(_tx("E2E-0001", "ACSC")), (_instruction(),)),
    )
    _margin(trace, absent_margin_assessment("qualified receipt, margin not assessed"))
    return trace


def scenario_unassessed_venue() -> dict[str, object]:
    """A determined outcome on a venue whose rulebook nobody has read."""
    trace: dict[str, object] = {}
    profile = absent_determination_profile("VENUE-UNREAD")
    outcome = classify_determination(
        profile=profile, instrument_is_contingent=True, determined=True
    )
    trace["determination"] = {
        "outcome": outcome.value,
        "obligation_finality_class": (
            obligation_finality_class(outcome).value
            if obligation_finality_class(outcome)
            else None
        ),
        "revocation_form": profile.revocation_form.value,
        "qualification_window_seconds": profile.qualification_window_seconds,
    }
    _cash_leg(
        trace,
        opening=D("10000000"),
        obligation=D("1000000"),
        determination_outcome=outcome,
    )
    _readback(trace, absent_readback("gate held; nothing released"))
    _margin(trace, absent_margin_assessment("gate held"))
    return trace


def scenario_clearing_fund_deficient() -> dict[str, object]:
    """A hard risk control, and the margin consequence it did not state."""
    trace: dict[str, object] = {}
    _cash_leg(
        trace,
        opening=D("10000000"),
        obligation=D("1000000"),
        clearing_fund_posted=D("250000"),
        clearing_fund_requirement=D("1000000"),
    )
    _readback(trace, absent_readback("gate held; nothing released"))
    _margin(
        trace,
        margin_impact_for_clearing_fund_deficiency(
            requirement=D("1000000"),
            posted=D("250000"),
            currency="USD",
            venue="CCP-A",
        ),
    )
    return trace


def _equity(
    *,
    allocated: Decimal | None,
    spans_record_date: bool = False,
    allocation_rule_published: bool = True,
) -> dict[str, object]:
    profile = MarketProfile(
        market_id="XCLR",
        settlement_cycle_days=1,
        close_out_regime=CloseOutRegime.MANDATORY_DEADLINE,
        close_out_deadline_days=3,
        allocation_rule_published=allocation_rule_published,
        provenance="Market rulebook, settlement and close-out provisions",
    )
    position = net_positions(
        (("SEC-A", D("6000")), ("SEC-A", D("-1000")), ("SEC-B", D("2000"))),
        market_id="XCLR",
        settlement_date_offset_days=1,
    )[0]
    result = settle_net_position(
        position,
        profile,
        allocated_quantity=allocated,
        spans_record_date=spans_record_date,
    )
    return {
        "position": {
            "security_id": position.security_id,
            "net_quantity": str(position.quantity),
            "constituent_trade_count": position.constituent_trade_count,
            "finality_class": position.finality_class.value,
        },
        "settlement": {
            "disposition": result.disposition.value,
            "allocated": str(result.allocated_quantity),
            "residual": str(result.residual.quantity) if result.residual else None,
            "is_fail": result.is_fail,
            "completed": result.completed,
            "rationale": result.rationale,
        },
        "breaks": [
            {"code": b.code.value, "detail": b.detail} for b in result.breaks
        ],
    }


def scenario_equity_partial_opaque() -> dict[str, object]:
    """Partial allocation on a market that does not publish its rule."""
    return {"equity": _equity(allocated=D("2000"), allocation_rule_published=False)}


def scenario_equity_record_date() -> dict[str, object]:
    """An open position across a corporate-action record date."""
    return {
        "equity": _equity(
            allocated=D("2000"), spans_record_date=True, allocation_rule_published=True
        )
    }


def scenario_equity_unreported() -> dict[str, object]:
    """No settlement outcome reported. Not a settled position."""
    return {"equity": _equity(allocated=None)}


SCENARIOS = {
    "clean-cash": scenario_clean_cash,
    "queued": scenario_queued,
    "silence": scenario_silence,
    "unsolicited": scenario_unsolicited,
    "partial-batch": scenario_partial_batch,
    "regression": scenario_regression,
    "contingent-qualified": scenario_contingent_qualified,
    "unassessed-venue": scenario_unassessed_venue,
    "clearing-fund-deficient": scenario_clearing_fund_deficient,
    "equity-partial-opaque": scenario_equity_partial_opaque,
    "equity-record-date": scenario_equity_record_date,
    "equity-unreported": scenario_equity_unreported,
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run(name: str) -> tuple[dict[str, object], bool]:
    """Run a scenario twice and report whether the two traces are identical."""
    first = SCENARIOS[name]()
    second = SCENARIOS[name]()
    deterministic = json.dumps(first, sort_keys=True) == json.dumps(
        second, sort_keys=True
    )
    return first, deterministic


def _print_human(name: str, trace: dict[str, object], deterministic: bool) -> None:
    print(f"\n=== {name} {'=' * max(0, 60 - len(name))}")
    doc = (SCENARIOS[name].__doc__ or "").strip().split("\n\n")[0]
    print(f"    {' '.join(doc.split())}\n")
    for stage, payload in trace.items():
        if payload is None:
            print(f"  {stage}: (not reached)")
            continue
        print(f"  {stage}:")
        for key, value in payload.items():  # type: ignore[union-attr]
            if key in ("rationale", "basis", "detail"):
                text = " ".join(str(value).split())
                clipped = text[:_TRUNCATE_AT]
                suffix = "..." if len(text) > _TRUNCATE_AT else ""
                print(f"    {key}: {clipped}{suffix}")
            elif key == "breaks":
                if not value:
                    print("    breaks: none")
                for b in value:  # type: ignore[union-attr]
                    detail = " ".join(str(b.get("detail", "")).split())
                    print(f"    break: {b['code']} - {detail[:110]}")
            else:
                print(f"    {key}: {value}")
    print(f"  determinism: {'IDENTICAL on replay' if deterministic else 'DIVERGED'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenarios", nargs="*", help="scenario names (default: all)")
    parser.add_argument("--json", action="store_true", help="emit JSON for diffing")
    parser.add_argument("--list", action="store_true", help="list scenario names")
    args = parser.parse_args()

    if args.list:
        for name, fn in SCENARIOS.items():
            doc = " ".join((fn.__doc__ or "").strip().split("\n")[0].split())
            print(f"{name:26} {doc}")
        return 0

    names = args.scenarios or list(SCENARIOS)
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        print(f"unknown scenario(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    results: dict[str, object] = {}
    failed_determinism: list[str] = []
    for name in names:
        try:
            trace, deterministic = run(name)
        except Exception as exc:
            print(f"{name}: RAISED {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        if not deterministic:
            failed_determinism.append(name)
        if args.json:
            results[name] = {"trace": trace, "deterministic": deterministic}
        else:
            _print_human(name, trace, deterministic)

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        print(f"\n{len(names)} scenario(s) run.")
        if failed_determinism:
            print(f"DETERMINISM FAILED: {', '.join(failed_determinism)}")
        else:
            print("All traces identical on replay.")

    return 1 if failed_determinism else 0


if __name__ == "__main__":
    raise SystemExit(main())
