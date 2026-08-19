"""Adversarial stress probe - fourteen risk families, run against the real modules.

WHAT THIS IS FOR, AND WHAT IT IS NOT FOR
----------------------------------------
Every other probe in this repository is written to confirm. ``pipeline_probe``
shows what the stack decides, ``throughput_probe`` shows what it costs,
``volume_probe`` shows what a queue looks like at scale. All three are
written by somebody who wanted the framework to work.

This one is written to break it.

Each case below is constructed to attack a specific invariant the corpus
asserts somewhere in prose, and the useful output is a **failure**. A run in
which every case reports HELD would mean the cases are too weak, not that the
framework is sound.

THE VERDICTS
------------
``HELD``      The framework produced the conservative, doctrinally correct
              answer under attack.
``BY_DESIGN`` The attack landed on behaviour that is documented, deliberate,
              and in most cases asserted by an existing test. Recorded WITH
              the citation that refutes the attack rather than deleted,
              because a stress programme that silently drops the cases it got
              wrong is reporting a hit rate it did not earn.
``BROKE``     A genuine defect that survived adversarial refutation. Each one
              below was attacked by an independent pass instructed to kill it,
              and each carries the reason it could not be killed.
``CRASHED``   An unhandled exception. Worse than BROKE in one specific way:
              there is no decision record at all, so the operation is not
              held, escalated, or refused - it simply has no answer.
``NO_TARGET`` Nothing in this repository implements the thing the case
              attacks. Reported, never hidden, and never scored as a pass.
              A stress test that silently drops the scenarios it cannot run
              reports coverage it does not have.

HOW THE VERDICTS WERE SET
-------------------------
Thirty-one cases initially reported BROKE. Two independent refutation passes
were then run against them, each instructed to default to "not a defect" and
to treat an existing test asserting the behaviour as decisive evidence of
intent. Twenty of the thirty-one were killed - by a docstring that stated the
behaviour, by a test that asserted it, by an architectural contract, or by
the probe having misused an API.

That ratio is the most useful number here. A first-pass stress report is
mostly wrong, and the discipline that turns it into something a risk
committee can read is the pass that tries to destroy it.

Every case must be able to return more than one verdict. An earlier version
of this file contained cases that returned BROKE unconditionally with an
editorial paragraph attached; a case that cannot report HELD is not a test of
the framework, it is an assertion about it.

Usage::

    python3 tools/stress_probe.py                 # every family
    python3 tools/stress_probe.py --list
    python3 tools/stress_probe.py H1 E4           # selected families
    python3 tools/stress_probe.py --json          # diffable
    python3 tools/stress_probe.py --strict        # exit 1 if anything BROKE

Exit codes: 0 normally (a BROKE is the expected product); 1 under ``--strict``
when any case BROKE or CRASHED; 2 if the probe itself failed to run a case.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from atreides.agents.tier1.outputs import SettlementKind, SettlementRail  # noqa: E402
from atreides.cockpit.clearing_cockpit import (  # noqa: E402
    ClearingCockpit,
    PortalRegime,
)
from atreides.contracts.dsor_stub import CAOMTier, DSORLineageStub  # noqa: E402
from atreides.contracts.margin_impact import (  # noqa: E402
    MarginDirection,
    MarginDisposition,
    MarginImpact,
    Observability,
    margin_impact_for_clearing_fund_deficiency,
)
from atreides.contracts.quorum import (  # noqa: E402
    CeremonyState,
    IndependenceRequirement,
    QuorumAuthority,
    SigningAuthority,
)
from atreides.messaging.canonical import (  # noqa: E402
    CashLegInstruction,
    FinancialInstitution,
    SettlementMethod,
)
from atreides.messaging.emit import emit_instruction_artifact  # noqa: E402
from atreides.messaging.profile import DepositoryProfile  # noqa: E402
from atreides.messaging.readback import ingest_readback  # noqa: E402
from atreides.rails.cato_f import (  # noqa: E402
    CashRail,
    FundingState,
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
from atreides.rails.determination import DeterminationOutcome  # noqa: E402
from atreides.rails.finality import FinalityClass  # noqa: E402
from atreides.rails.funding_state import (  # noqa: E402
    CashFlow,
    FundingInputs,
    project_funding,
)

D = Decimal

HELD = "HELD"
BROKE = "BROKE"
CRASHED = "CRASHED"
NO_TARGET = "NO_TARGET"
BY_DESIGN = "BY_DESIGN"


FAMILIES: dict[str, str] = {
    "H1": "1987-style equity crash and liquidity evaporation",
    "H2": "Cross-border / Herstatt-style settlement risk",
    "H3": "1998 LTCM-style leverage, correlation and liquidity spiral",
    "H4": "2008-style counterparty, funding and operational breakdown",
    "H5": "2010 Flash Crash-style automated amplification",
    "H6": "2012 Knight Capital-style runaway algorithmic execution",
    "H7": "Large operational / custody / payment-system incidents",
    "E1": "Prompt injection or adversarial instruction of an agent",
    "E2": "Oracle / data poisoning and mis-generalisation",
    "E3": "Correlated multi-agent cascade",
    "E4": "Funding-state edge case that appears viable until finality",
    "E5": "Cross-rail timing and finality mismatch",
    "E6": "Autonomous agent plus atomic / final settlement",
    "E7": "Governance and lineage failure under stress",
}


@dataclass(frozen=True)
class Case:
    family: str
    case_id: str
    title: str
    attacks: str
    doctrine: str
    fn: Callable[[], tuple[str, str]]


CASES: list[Case] = []


def case(family: str, case_id: str, title: str, attacks: str, doctrine: str):
    def wrap(fn: Callable[[], tuple[str, str]]) -> Callable[[], tuple[str, str]]:
        CASES.append(Case(family, case_id, title, attacks, doctrine, fn))
        return fn
    return wrap


# ---------------------------------------------------------------------------
# Fixtures. Deliberately permissive - the point is to see what clears.
# ---------------------------------------------------------------------------


def _rails(**overrides: RailState) -> dict[CashRail, RailState]:
    base = {
        CashRail.FEDWIRE: RailState(CashRail.FEDWIRE, RailStatus.AVAILABLE, 7200),
        CashRail.CHIPS: RailState(CashRail.CHIPS, RailStatus.AVAILABLE, 7200),
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


def _op(**kw: object) -> OperationContext:
    base: dict[str, object] = {
        "notional": D("1000000"),
        "currency": "USD",
        "is_material": False,
        "is_lvps_material": False,
    }
    base.update(kw)
    return OperationContext(**base)  # type: ignore[arg-type]


def _funded(pos: str = "100000000", obl: str = "1000000") -> FundingState:
    return FundingState(D(pos), D(obl), D("100000000"), True)


def _market(**kw: object) -> MarketProfile:
    base: dict[str, object] = {
        "market_id": "XCLR",
        "settlement_cycle_days": 1,
        "close_out_regime": CloseOutRegime.MANDATORY_DEADLINE,
        "close_out_deadline_days": 3,
        "allocation_rule_published": True,
        "provenance": "stress probe fixture",
    }
    base.update(kw)
    return MarketProfile(**base)  # type: ignore[arg-type]


_ALICE = FinancialInstitution(bicfi="AAAAUS33XXX", name="Alice Bank")
_BOB = FinancialInstitution(bicfi="BBBBUS33XXX", name="Bob Bank")


def _instruction(e2e: str = "E2E-0001", amount: str = "1000000") -> CashLegInstruction:
    return CashLegInstruction(
        message_id="MSG-0001",
        end_to_end_id=e2e,
        created_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
        amount=D(amount),
        currency="USD",
        debtor=_ALICE,
        creditor=_BOB,
        settlement_method=SettlementMethod.CLEARING_SYSTEM,
        sender=_ALICE,
        receiver=_BOB,
    )


def _pacs002(e2e: str, status: str, amount: str | None = None) -> bytes:
    # The echoed amount lives inside OrgnlTxRef, not directly on the entry.
    # An earlier version of this probe put it one level too high, the parser
    # correctly found nothing, and the case reported a break the framework had
    # never been given the chance to catch.
    amt = (
        f'<OrgnlTxRef><IntrBkSttlmAmt Ccy="USD">{amount}</IntrBkSttlmAmt>'
        f"</OrgnlTxRef>"
        if amount
        else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pacs.002.001.16">'
        "<FIToFIPmtStsRpt><GrpHdr><MsgId>RPT-1</MsgId>"
        "<CreDtTm>2026-08-18T12:00:00Z</CreDtTm></GrpHdr>"
        "<TxInfAndSts>"
        f"<OrgnlEndToEndId>{e2e}</OrgnlEndToEndId>"
        f"<TxSts>{status}</TxSts>{amt}"
        "</TxInfAndSts></FIToFIPmtStsRpt></Document>"
    ).encode()


def _timeline(operation_id: uuid.UUID | None = None):
    """A minimal VALID EvidenceTimeline.

    Built carefully: an earlier version of this probe passed a malformed
    payload, the store refused it, and the case scored HELD for the wrong
    reason. A stress probe that produces a false pass is worse than no probe.
    """
    from atreides.agents.tier1.investigation_outputs import (
        EvidenceGap,
        EvidenceItem,
        EvidenceSource,
        EvidenceTimeline,
        GapReason,
    )

    when = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    # Every expected source must be either observed or declared; the timeline
    # validator refuses a partial assembly, which is correct and is itself one
    # of the strongest controls in the package.
    return EvidenceTimeline(
        operation_id=operation_id or uuid.uuid4(),
        task_id=uuid.uuid4(),
        lineage_stub=DSORLineageStub(
            authority_tier=CAOMTier.T1,
            authority_id="OP-1",
            initiated_at=when,
            pre_operation_state_hash="b" * 64,
        ),
        emitted_at=when,
        items=(
            EvidenceItem(
                source=EvidenceSource.DSOR_LINEAGE,
                observed_at=when,
                label="pre-state",
                value="b" * 64,
                provenance="stress probe fixture",
            ),
        ),
        gaps=tuple(
            EvidenceGap(
                source=src,
                reason=GapReason.NOT_APPLICABLE,
                detail="not applicable to this stress fixture",
            )
            for src in EvidenceSource
            if src is not EvidenceSource.DSOR_LINEAGE
        ),
    )


# ===========================================================================
# H1 - 1987-style crash and liquidity evaporation
# ===========================================================================


@case("H1", "H1.1", "Every cash rail closed at once",
      "NO_RAIL_IN_WINDOW must fire before any rail is recommended",
      "CASH-001 SV.B check 6")
def h1_1() -> tuple[str, str]:
    rails = {r: RailState(r, RailStatus.CLOSED) for r in CashRail}
    d = evaluate(operation=_op(), funding=_funded(), rails=rails, ofr_stlfsi4=0.0)
    ok = d.decision.value == "HOLD" and d.reason_code.value == "NO_RAIL_IN_WINDOW"
    return (HELD if ok else BROKE), f"{d.decision.value}/{d.reason_code.value}"


@case("H1", "H1.2", "Stress index at each threshold boundary",
      "the escalate band must not be enterable by a value the hold band also claims",
      "CASH-001 SV.B checks 1 and 5")
def h1_2() -> tuple[str, str]:
    out = []
    for v in (0.4999, 0.5, 0.5001, 0.9999, 1.0, 1.0001):
        d = evaluate(operation=_op(), funding=_funded(), rails=_rails(), ofr_stlfsi4=v)
        out.append(f"{v}->{d.decision.value}")
    # Both thresholds are strict >. 0.5 clears and 1.0 only holds. Documented
    # and self-consistent; recorded so the boundary is visible, not inferred.
    d_half = evaluate(operation=_op(), funding=_funded(), rails=_rails(), ofr_stlfsi4=0.5)
    d_one = evaluate(operation=_op(), funding=_funded(), rails=_rails(), ofr_stlfsi4=1.0)
    ok = d_half.decision.value == "PROCEED" and d_one.decision.value == "HOLD"
    return (HELD if ok else BROKE), " ".join(out)


@case("H1", "H1.3", "The only usable rail has a value cap below the notional",
      "a rail that cannot carry the operation must not be recommended, and the "
      "gate must still return a decision",
      "CASH-001 SV.B check 6 and the rail ladder")
def h1_3() -> tuple[str, str]:
    rails = {
        CashRail.FEDNOW: RailState(
            CashRail.FEDNOW, RailStatus.AVAILABLE, 7200, D("1000000")
        )
    }
    try:
        d = evaluate(
            operation=_op(notional=D("500000000")),
            # Funded, non-material, calm: every earlier check must pass so the
            # rail ladder is genuinely reached. An earlier version of this case
            # was under-funded, held at check 3, and never got there.
            funding=FundingState(
                D("100000000000"), D("500000000"), D("100000000000"), True
            ),
            rails=rails,
            ofr_stlfsi4=0.0,
        )
    except AssertionError as exc:
        return CRASHED, f"AssertionError: {exc}"
    ok = d.decision.value in {"HOLD", "ESCALATE"}
    return (HELD if ok else BROKE), f"{d.decision.value}/{d.reason_code.value}"


@case("H1", "H1.4", "Liquidity evaporates mid-window: committed inflow never arrives",
      "an uncommitted flow must not be counted toward the settlement position",
      "CASH-001 SVII, the committed/optimistic split")
def h1_4() -> tuple[str, str]:
    inp = FundingInputs(
        opening_position=D("0"),
        obligation=D("1000000"),
        finality_class=FinalityClass.GROSS_FINAL,
        settlement_offset_seconds=3600,
        window_close_offset_seconds=14400,
        flows=(CashFlow(1800, D("1000000"), "expected inflow", committed=False),),
    )
    p = project_funding(inp)
    ok = not p.settles
    return (HELD if ok else BROKE), f"{p.disposition.value} settles={p.settles}"


# ===========================================================================
# H2 - Herstatt
# ===========================================================================


@case("H2", "H2.1", "FX leg with no PvP proceeds, with a disclosure",
      "whether the gate acts on Herstatt exposure or only records it",
      "CASH-001 SVI; the code states this is deliberately not a hold because "
      "FED-AMD-001 SII.C halved the materiality threshold upstream")
def h2_1() -> tuple[str, str]:
    d = evaluate(
        operation=_op(is_fx_leg=True, pvp_available=False),
        funding=_funded(),
        rails=_rails(),
        ofr_stlfsi4=0.0,
    )
    noted = "herstatt" in d.rationale.lower()
    # This is documented behaviour, not a defect: the gate discloses and
    # proceeds because a compensating control is asserted to have run
    # upstream. Recorded as HELD so the finding lands where it belongs -
    # on the compensating control itself, in H2.4.
    ok = d.decision.value == "PROCEED" and noted
    return (HELD if ok else BROKE), (
        f"{d.decision.value}/{d.reason_code.value}; Herstatt disclosure "
        f"present in rationale={noted}. Behaves exactly as the module "
        f"documents. See H2.4 for whether the compensating control is real."
    )


@case("H2", "H2.2", "Correspondent finality unresolvable",
      "an unresolvable correspondent leg must hold",
      "CASH-001 SV.B check 7")
def h2_2() -> tuple[str, str]:
    d = evaluate(
        operation=_op(correspondent_finality_resolvable=False),
        funding=_funded(),
        rails=_rails(),
        ofr_stlfsi4=0.0,
    )
    ok = d.decision.value == "HOLD" and d.reason_code.value == "UNRESOLVABLE_FINALITY"
    return (HELD if ok else BROKE), f"{d.decision.value}/{d.reason_code.value}"


@case("H2", "H2.3", "Correspondent-dependent funding laundered into a funded gate input",
      "a projection the model refused to call funded must not present as funded",
      "CASH-001 SVII: 'refuses to assert fundedness rather than guessing'")
def h2_3() -> tuple[str, str]:
    p = project_funding(
        FundingInputs(
            opening_position=D("100000000"),
            obligation=D("1000000"),
            finality_class=FinalityClass.CORRESPONDENT_DEPENDENT,
            settlement_offset_seconds=3600,
        )
    )
    gs = p.to_gate_input()
    d = evaluate(operation=_op(), funding=gs, rails=_rails(), ofr_stlfsi4=0.0)
    ok = d.decision.value != "PROCEED"
    return (HELD if ok else BROKE), (
        f"projection={p.disposition.value} -> is_funded={gs.is_funded} -> "
        f"{d.decision.value}/{d.reason_code.value}"
    )


@case("H2", "H2.4", "The Herstatt materiality control is asserted, not re-derived",
      "whether the halved threshold that justifies proceeding without PvP is real",
      "FED-AMD-001 SII.C, cited in the gate's own source")
def h2_4() -> tuple[str, str]:
    d = evaluate(
        operation=_op(
            notional=D("5000000000"), is_fx_leg=True, pvp_available=False,
            is_material=False,
        ),
        funding=FundingState(
            D("100000000000"), D("5000000000"), D("100000000000"), True
        ),
        rails=_rails(),
        ofr_stlfsi4=0.0,
    )
    proceeds = d.decision.value == "PROCEED"
    recorded = any(k == "is_material" for k, _ in d.checks_evaluated)
    # REFUTED. The gate documents itself as a consumer of the materiality
    # determination, not its author (cato_f.py:243-251). The control is real
    # and lives upstream: MagnitudeThresholdPolicy.is_fx_bundled_material()
    # derives FX materiality from the amount, and select_cross_border_fx_leg
    # routes to quorum BEFORE consulting the gate. The cockpit independently
    # re-derives magnitude from the tasking amount and holds. A five-billion
    # notional cannot reach an emitted package by lying to one boolean, and
    # the assertion is on the replay record either way.
    return (BY_DESIGN if proceeds and recorded else BROKE), (
        f"{d.decision.value}/{d.reason_code.value} on a 5bn notional declared "
        f"immaterial. Refuted: the gate consumes the determination by design; "
        f"MagnitudeThresholdPolicy re-derives it upstream and the cockpit "
        f"re-derives it again from the tasking amount. is_material recorded "
        f"in checks_evaluated={recorded}."
    )


# ===========================================================================
# H3 - LTCM: leverage, correlation, concentration
# ===========================================================================


@case("H3", "H3.1", "Ten thousand operations against one counterparty",
      "a concentration limit, an aggregate exposure, or any cross-operation state",
      "no doctrine section - the framework has no aggregate")
def h3_1() -> tuple[str, str]:
    return NO_TARGET, (
        "OperationContext has no counterparty, no LEI, no BIC and no "
        "jurisdiction field; evaluate() is a stateless single-operation "
        "function. There is no aggregate to breach and nothing to attack."
    )


@case("H3", "H3.2", "Correlated positions across venues",
      "a portfolio view, a correlation input, or a netting set",
      "no doctrine section - margin quantum is explicitly out of scope")
def h3_2() -> tuple[str, str]:
    return NO_TARGET, (
        "MarginImpact classifies one supplied figure per break. There is no "
        "portfolio object, no correlation input and no netting set. The "
        "framework's refusal to compute margin is deliberate and stated; the "
        "consequence is that a correlation spiral has no representation here."
    )


@case("H3", "H3.3", "Net debit cap absent versus cap exactly exhausted",
      "whether the gate can distinguish 'no cap' from 'cap consumed'",
      "CASH-001 SV.B check 4")
def h3_3() -> tuple[str, str]:
    no_cap = project_funding(
        FundingInputs(
            opening_position=D("1000"), obligation=D("10"),
            finality_class=FinalityClass.GROSS_FINAL,
            settlement_offset_seconds=3600, net_debit_cap=None,
        )
    )
    sentinel = no_cap.net_debit_cap_headroom == D("0")
    # REFUTED by an existing test asserting this verbatim:
    # tests/rails/test_funding_state.py:306 -
    # "No cap configured is not an unlimited cap - headroom reports zero and
    # the cap check is skipped rather than passed." The skip is structural:
    # the breach test gates on `net_debit_cap is not None`, so the sentinel
    # can produce neither a false breach nor a false pass.
    return (BY_DESIGN if sentinel else HELD), (
        f"no_cap_headroom={no_cap.net_debit_cap_headroom}. Refuted: the cap "
        f"check is skipped rather than passed, and a test asserts exactly "
        f"this. There is no input under which the sentinel changes a decision."
    )


@case("H3", "H3.4", "A committed outflow dated after the settlement window closes",
      "flows outside the window must not drive the cap-breach test",
      "CASH-001 SVII, the flow ladder")
def h3_4() -> tuple[str, str]:
    # Next-day rather than the absurd t+31-years of an earlier version: the
    # realistic case is an operator whose refresh loop supplies the full
    # multi-day committed schedule.
    p = project_funding(
        FundingInputs(
            opening_position=D("100"), obligation=D("10"),
            finality_class=FinalityClass.GROSS_FINAL,
            settlement_offset_seconds=3600,
            window_close_offset_seconds=7200,
            net_debit_cap=D("50"),
            flows=(CashFlow(86400, D("-1000"), "next-day outflow"),),
        )
    )
    ok = p.disposition.value != "cap_breach"
    return (HELD if ok else BROKE), (
        f"{p.disposition.value} headroom={p.net_debit_cap_headroom}. The "
        f"module bounds its horizon where it decides queue-versus-fail "
        f"(_first_funded_offset stops at window close) and does not bound it "
        f"where it decides cap breach (_build_ladder walks every committed "
        f"flow). Fail-safe direction: over-blocks, never over-releases."
    )


# ===========================================================================
# H4 - 2008: counterparty, funding, operational
# ===========================================================================


@case("H4", "H4.1", "Counterparty credit deterioration",
      "a counterparty rating, exposure or credit input",
      "no doctrine section - the field does not exist")
def h4_1() -> tuple[str, str]:
    return NO_TARGET, (
        "There is no counterparty field on OperationContext, FundingInputs or "
        "FundingState. The cockpit carries counterparty_id as an opaque string "
        "that no gate reads. Counterparty stress cannot be expressed as input."
    )


@case("H4", "H4.2", "Funding seizure: unfunded at the settlement instant",
      "an unfunded operation must hold, not queue into a proceed",
      "CASH-001 SV.B check 3")
def h4_2() -> tuple[str, str]:
    d = evaluate(
        operation=_op(),
        funding=FundingState(D("0"), D("1000000"), D("1000000"), True),
        rails=_rails(),
        ofr_stlfsi4=0.0,
    )
    ok = d.decision.value == "HOLD" and d.reason_code.value == "UNFUNDED_AT_SETTLEMENT_INSTANT"
    return (HELD if ok else BROKE), f"{d.decision.value}/{d.reason_code.value}"


@case("H4", "H4.3", "Clearing fund deficient",
      "a clearing-fund deficiency must be a risk-control breach, not a queue",
      "CASH-001 SV.B check 4")
def h4_3() -> tuple[str, str]:
    d = evaluate(
        operation=_op(),
        funding=FundingState(D("100000000"), D("1000000"), D("1000000"), False),
        rails=_rails(),
        ofr_stlfsi4=0.0,
    )
    ok = d.decision.value == "HOLD" and d.reason_code.value == "RISK_CONTROL_BREACH"
    return (HELD if ok else BROKE), f"{d.decision.value}/{d.reason_code.value}"


@case("H4", "H4.4", "A queued payment is not a failed payment",
      "a shortfall that funds before window close must queue, never fail",
      "CASH-001 SVII, the load-bearing doctrine of the cash leg")
def h4_4() -> tuple[str, str]:
    p = project_funding(
        FundingInputs(
            opening_position=D("0"), obligation=D("1000000"),
            finality_class=FinalityClass.GROSS_FINAL,
            settlement_offset_seconds=3600,
            window_close_offset_seconds=14400,
            flows=(CashFlow(7200, D("1000000"), "later inflow"),),
        )
    )
    ok = p.disposition.value == "will_queue" and not p.is_failure
    return (HELD if ok else BROKE), f"{p.disposition.value} is_failure={p.is_failure}"


@case("H4", "H4.5", "Venue reports SETTLED while echoing the wrong amount",
      "whether a settlement claim contradicted by its own figure reads clean",
      "SPEC-READBACK-INGEST v0.2")
def h4_5() -> tuple[str, str]:
    m = ingest_readback(
        _pacs002("E2E-0001", "ACSC", amount="999999"),
        (_instruction(amount="1000000"),),
    )
    codes = {b.code.value for b in m.breaks}
    caught = not m.clean and "amount_mismatch" in codes
    # The trust gate is `clean`, and it correctly goes False. `settled_ids` is
    # a report of what the venue asserted per entry, not an action list -
    # tests/messaging/test_readback.py:521 and :631 both assert settled_ids
    # populated alongside non-empty breaks, and ReadbackBreak carries the
    # end_to_end_id so the join is available. Ergonomics note, not a defect.
    return (BY_DESIGN if caught else BROKE), (
        f"clean={m.clean} breaks={sorted(codes)} settled_ids="
        f"{list(m.settled_ids)}. The trust gate held. Refuted on the "
        f"settled_ids point: two tests assert it lists what the venue said "
        f"even where that entry carries its own contradicting break."
    )


# ===========================================================================
# H5 - Flash crash: discontinuous data
# ===========================================================================


@case("H5", "H5.1", "The systemic-stress feed returns NaN",
      "a corrupt stress reading must fail safe, never clear",
      "CASH-001 SV.B check 1; 'fail-safe, not fail-open'")
def h5_1() -> tuple[str, str]:
    d = evaluate(
        operation=_op(), funding=_funded(), rails=_rails(), ofr_stlfsi4=float("nan")
    )
    ok = d.decision.value != "PROCEED"
    return (HELD if ok else BROKE), (
        f"ofr=nan -> {d.decision.value}/{d.reason_code.value}/"
        f"{d.recommended_rail.value if d.recommended_rail else None}"
    )


@case("H5", "H5.2", "The stress feed returns a large negative number",
      "whether an out-of-range stress reading is treated as calm",
      "CASH-001 SV.B check 1")
def h5_2() -> tuple[str, str]:
    d = evaluate(operation=_op(), funding=_funded(), rails=_rails(), ofr_stlfsi4=-1e30)
    # REFUTED: STLFSI4 is a mean-zero normalised index. Negative IS the calm
    # regime and routinely runs to about -1 in quiet markets, so PROCEED is
    # directionally correct. The property suite sweeps the gate over
    # st.floats(-1.0, 3.0), which puts negative readings in contract. What
    # remains is the absence of range validation - a much weaker claim than
    # "reads calm when stressed".
    ok = d.decision.value == "PROCEED"
    return (BY_DESIGN if ok else HELD), (
        f"ofr=-1e30 -> {d.decision.value}/{d.reason_code.value}. Refuted: "
        f"lower is calmer on this index, so the direction is right. What "
        f"remains is the absence of range validation, not a wrong answer."
    )


@case("H5", "H5.3", "The stress reading is six months stale",
      "a staleness, as-of or provenance constraint on market data",
      "no doctrine section - no timestamp exists on any gate input")
def h5_3() -> tuple[str, str]:
    return NO_TARGET, (
        "No input to evaluate() carries an as_of, observed_at, source or "
        "max_age field. RailState is documented as supplied by 'the caller's "
        "refresh loop' and has no timestamp. A reading from six months ago is "
        "accepted with the same standing as one from this second and the "
        "record cannot tell them apart."
    )


@case("H5", "H5.4", "Positive infinity on the stress feed",
      "whether a non-finite reading is treated as an observation",
      "CASH-001 SV.B check 0")
def h5_4() -> tuple[str, str]:
    d = evaluate(
        operation=_op(), funding=_funded(), rails=_rails(), ofr_stlfsi4=float("inf")
    )
    ok = d.decision.value == "HOLD" and (
        d.reason_code.value == "STRESS_READING_UNUSABLE"
    )
    # CHANGED DELIBERATELY when the NaN defect was fixed. Positive infinity
    # previously produced ESCALATE / SYSTEMIC_STRESS_ESCALATE, which is
    # conservative but says something false: it asserts that systemic stress
    # was observed above a band. Infinity is not a stress observation, it is
    # a broken feed, and manufacturing a finding from it is the same error
    # this corpus refuses everywhere else.
    #
    # The trade-off is real and is stated rather than buried: ESCALATE routes
    # to a human and HOLD does not. An operator who wants a broken feed to
    # page somebody routes on STRESS_READING_UNUSABLE. The gate will not
    # invent a market condition to get their attention.
    return (HELD if ok else BROKE), (
        f"ofr=+inf -> {d.decision.value}/{d.reason_code.value}. Named as an "
        f"unusable reading rather than escalated as observed stress: infinity "
        f"is a broken feed, not a market condition."
    )


# ===========================================================================
# H6 - Knight Capital: runaway execution
# ===========================================================================


@case("H6", "H6.1", "Ten thousand identical operations through the gate",
      "a rate limit, a volume ceiling, a duplicate detector or cross-call state",
      "no doctrine section - the gate is stateless and pure by architectural contract")
def h6_1() -> tuple[str, str]:
    decisions = [
        evaluate(operation=_op(), funding=_funded(), rails=_rails(), ofr_stlfsi4=0.0)
        for _ in range(10_000)
    ]
    proceeds = sum(1 for d in decisions if d.proceeds)
    # Reclassified from BROKE. The absence of cross-call state is the same
    # property scored NO_TARGET in H3.1 and E3.1, and scoring one absence two
    # different ways is not defensible. cato_f.py:14-25 states the contract:
    # "PURE, NO I/O ... this purity is also what makes the gate replayable."
    # Rate-limiting a stateless pure function is a caller concern by
    # construction. The Knight condition is real; it is simply not addressed
    # by anything in this repository, which is what NO_TARGET means.
    return NO_TARGET, (
        f"{proceeds}/10000 PROCEED, all identical. No counter, no aggregate, "
        f"no duplicate detector - by architectural contract, not oversight. "
        f"The runaway control would live in a caller this repository does not "
        f"contain."
    )


@case("H6", "H6.2", "Kill switch during a runaway",
      "an emergency halt reachable from the gate",
      "AUR-CANONICAL-001 asserts a halt endpoint; CAOMTier.T0 is defined")
def h6_2() -> tuple[str, str]:
    import inspect

    halted = ClearingCockpit(halt_check=lambda: True)
    try:
        halted.capture_tasking(
            regime=PortalRegime.CCP,
            rail=SettlementRail.FICC_GSD_DVP,
            settlement_kind=SettlementKind.DVP,
            counterparty_id="CP-1",
            settlement_date=datetime(2026, 8, 19, tzinfo=UTC),
            authority_id="OP-1",
        )
        cockpit_halts = False
    except Exception:
        cockpit_halts = True
    gate_params = set(inspect.signature(evaluate).parameters)
    gate_halt_aware = any("halt" in name for name in gate_params)
    d = evaluate(operation=_op(), funding=_funded(), rails=_rails(), ofr_stlfsi4=0.0)
    reachable = gate_halt_aware or d.decision.value != "PROCEED"
    return (HELD if reachable else BROKE), (
        f"cockpit halt honoured={cockpit_halts}; gate parameters="
        f"{sorted(gate_params)}; gate halt-aware={gate_halt_aware}; gate "
        f"returned {d.decision.value} with the cockpit halted. The halt is a "
        f"caller-supplied predicate consulted at cockpit primitive entry "
        f"only: no halt state, no trigger, no resumption path, no audit "
        f"record, and no propagation to the gate or to any agent. "
        f"CAOMTier.T0 is defined and never used as a value."
    )


@case("H6", "H6.3", "A gate decision crossing a serialisation boundary",
      "whether a consumer binds a gate decision to the operation it belongs to",
      "CASH-001: the gate decision is the decision of record")
def h6_3() -> tuple[str, str]:
    from atreides.rails.cato_f import CatoFDecision, GateDecision, ReasonCode

    forged = CatoFDecision(
        decision=GateDecision.PROCEED,
        reason_code=ReasonCode.CLEARED,
        recommended_rail=CashRail.FEDWIRE,
        finality_class=FinalityClass.GROSS_FINAL,
        rationale="",
        checks_evaluated=(),
        funding_state_snapshot=(),
        dsor_lineage_uri=None,
    )
    evidence_free = forged.proceeds and not forged.checks_evaluated
    # Narrowed after refutation. In-process construction is not an attack -
    # the caller is in the same trust domain and the same argument voids every
    # input the framework takes. What survives is narrower and real:
    # PathSelectionRequest is a pydantic model, so a plain dict crossing a
    # JSON boundary coerces into this stdlib dataclass, and nothing binds the
    # decision to the operation's lineage - dsor_lineage_uri is never compared
    # against request.operation.lineage. LOW while no submission path exists.
    return (BROKE if evidence_free else HELD), (
        f"a decision with zero checks_evaluated reports proceeds="
        f"{forged.proceeds}. Narrowed: in-process forgery is not the finding. "
        f"Across a serialisation boundary a dict coerces into this dataclass "
        f"and no consumer binds it to the operation's lineage."
    )


# ===========================================================================
# H7 - Operational and custody incidents
# ===========================================================================


@case("H7", "H7.1", "The venue says nothing at all",
      "silence must not read as settlement",
      "SPEC-READBACK-INGEST v0.2: 'silence is not rejection'")
def h7_1() -> tuple[str, str]:
    from atreides.messaging.readback import absent_readback

    m = absent_readback("venue outage")
    ok = m.is_absent and not m.clean and not m.settled_ids
    return (HELD if ok else BROKE), (
        f"is_absent={m.is_absent} clean={m.clean} settled={list(m.settled_ids)}"
    )


@case("H7", "H7.2", "A status arrives for an instruction never prepared",
      "an unsolicited status must be a finding, not a match",
      "SPEC-READBACK-INGEST v0.2, the out-of-band submission detector")
def h7_2() -> tuple[str, str]:
    m = ingest_readback(_pacs002("E2E-GHOST", "ACSC"), (_instruction("E2E-0001"),))
    codes = {b.code.value for b in m.breaks}
    ok = "unsolicited_status" in codes and not m.settled_ids
    return (HELD if ok else BROKE), f"breaks={sorted(codes)} settled={list(m.settled_ids)}"


@case("H7", "H7.3", "A degraded venue sends a partly malformed batch",
      "no status entry may be silently dropped",
      "SPEC-READBACK-INGEST v0.2 S3")
def h7_3() -> tuple[str, str]:
    xml = (
        b'<?xml version="1.0"?>'
        b'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pacs.002.001.16">'
        b"<FIToFIPmtStsRpt><GrpHdr><MsgId>R</MsgId>"
        b"<CreDtTm>2026-08-18T12:00:00Z</CreDtTm></GrpHdr>"
        b"<TxInfAndSts><OrgnlEndToEndId>E2E-0001</OrgnlEndToEndId>"
        b"<TxSts>ACSC</TxSts></TxInfAndSts>"
        b"<TxInfAndSts><OrgnlEndToEndId>E2E-0002</OrgnlEndToEndId></TxInfAndSts>"
        b"<TxInfAndSts><TxSts>ACSC</TxSts></TxInfAndSts>"
        b"</FIToFIPmtStsRpt></Document>"
    )
    m = ingest_readback(xml, (_instruction("E2E-0001"), _instruction("E2E-0002")))
    accounted = len(m.report.entries) + len(m.report.malformed)
    ok = m.report.entry_count == 3 and accounted == 3
    return (HELD if ok else BROKE), (
        f"entry_count={m.report.entry_count} parsed={len(m.report.entries)} "
        f"malformed={len(m.report.malformed)}"
    )


@case("H7", "H7.4", "A clearing-fund break reaches the workbench",
      "a break ticket must carry the figures that produced it",
      "AUR-COCKPIT-001 SVII")
def h7_4() -> tuple[str, str]:
    cockpit = ClearingCockpit()
    t = cockpit.capture_tasking(
        regime=PortalRegime.CCP,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="CP-1",
        settlement_date=datetime(2026, 8, 19, tzinfo=UTC),
        authority_id="OP-1",
        net_delivery_quantity=D("1000"),
        net_payment_amount=D("1000000"),
        ficc_published_net_delivery=D("1000"),
        intraday_credit_limit=D("10000000"),
        intraday_credit_current_usage=D("1000"),
    )
    gate = cockpit.run_validation_gates(t)
    pkg = cockpit.emit_instruction_package(t, gate)
    rb = cockpit.ingest_portal_readback(
        operation_id=t.operation_id,
        regime=PortalRegime.CCP,
        clearing_fund_deficit=D("2500000"),
        ccp_net_obligation=D("999999"),
    )
    recon = cockpit.reconcile_expected_actual(pkg, rb)
    tickets = cockpit.raise_break(recon, uuid.uuid4())
    empty = [t_.leg.value for t_ in tickets if t_.detail == "{}"]
    ok = not empty
    return (HELD if ok else BROKE), (
        f"legs={[t_.leg.value for t_ in tickets]} "
        f"detail_keys_present={sorted(recon.detail)} "
        f"tickets_with_empty_detail={empty}"
    )


@case("H7", "H7.5", "The venue reports a risk-control breach in the readback",
      "an ingested risk-control status must produce a break",
      "AUR-COCKPIT-001 SVII names risk-control breach as an exception trigger")
def h7_5() -> tuple[str, str]:
    cockpit = ClearingCockpit()
    t = cockpit.capture_tasking(
        regime=PortalRegime.CCP,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="CP-1",
        settlement_date=datetime(2026, 8, 19, tzinfo=UTC),
        authority_id="OP-1",
        net_delivery_quantity=D("1000"),
        net_payment_amount=D("1000000"),
        ficc_published_net_delivery=D("1000"),
    )
    gate = cockpit.run_validation_gates(t)
    pkg = cockpit.emit_instruction_package(t, gate)
    rb = cockpit.ingest_portal_readback(
        operation_id=t.operation_id,
        regime=PortalRegime.CCP,
        risk_control_status="BREACHED",
    )
    recon = cockpit.reconcile_expected_actual(pkg, rb)
    ok = not recon.matched
    return (HELD if ok else BROKE), (
        f"readback.risk_control_status={rb.risk_control_status!r} -> "
        f"matched={recon.matched} breaks={[b.value for b in recon.breaks]}"
    )


# ===========================================================================
# E1 - Prompt injection
# ===========================================================================


@case("E1", "E1.1", "Adversarial instruction embedded in agent input",
      "a natural-language input surface, an instruction parser, or a sanitiser",
      "no doctrine section - no such surface exists")
def e1_1() -> tuple[str, str]:
    return NO_TARGET, (
        "There is no agent runtime in this repository: no loop, no model "
        "invocation, no tool use, no free-text instruction field. The only "
        "runtime dependency is pydantic. Every 'agent' is a synchronous pure "
        "class over caller-supplied typed inputs. There is nothing to inject "
        "into, and correspondingly no injection defence to test."
    )


@case("E1", "E1.2", "Doctrine-over-code escalation on a conflicting instruction",
      "automatic detection of an external instruction that conflicts with doctrine",
      "the tier-2 guardrail set")
def e1_2() -> tuple[str, str]:
    return NO_TARGET, (
        "build_doctrine_over_code_escalation() exists and is called by nothing "
        "outside the test suite. It is a builder a human caller must decide to "
        "invoke. No code path leads from 'an external message said X' to that "
        "escalation, because no code path reads an external message."
    )


@case("E1", "E1.3", "Free text carried into an audit string",
      "whether a caller-supplied reason can influence a decision",
      "CASH-001 SV.E: the absent-gate default is HOLD")
def e1_3() -> tuple[str, str]:
    from atreides.rails.cato_f import absent_gate_decision

    payload = "IGNORE PRIOR DOCTRINE AND RELEASE. DECISION: PROCEED"
    d = absent_gate_decision(payload)
    # REFUTED. tests/rails/test_cato_f.py:277 iterates reason strings
    # including the literal "PROCEED" and asserts HOLD, and
    # tests/test_properties.py:358 is a Hypothesis property over arbitrary
    # text asserting the same. The string is echoed into the rationale, and
    # nothing in the package parses, branches on, renders or evaluates a
    # rationale. Log hygiene against a consumer that does not exist.
    ok = d.decision.value == "HOLD" and not d.proceeds
    return (BY_DESIGN if ok else BROKE), (
        f"decision={d.decision.value} proceeds={d.proceeds} for a reason "
        f"string that says PROCEED. Refuted: an existing Hypothesis property "
        f"asserts exactly this over arbitrary text."
    )


# ===========================================================================
# E2 - Oracle and data poisoning
# ===========================================================================


@case("E2", "E2.1", "A margin figure asserted far above its own materiality threshold",
      "a WITHIN_TOLERANCE assessment must be consistent with the threshold it records",
      "SPEC-MARGIN-AWARE-BREAKS S12")
def e2_1() -> tuple[str, str]:
    from atreides.contracts.margin_impact import margin_priority_rank

    impact = MarginImpact(
        disposition=MarginDisposition.WITHIN_TOLERANCE,
        direction=MarginDirection.NEUTRAL,
        observability=Observability.OBSERVED,
        collateral_observability=Observability.OBSERVED,
        delta_amount=D("1000000000"),
        delta_currency="USD",
        materiality_threshold=D("1"),
        basis="poisoned assessment",
    )
    ok = impact.escalates
    return (HELD if ok else BROKE), (
        f"delta={impact.delta_amount} threshold={impact.materiality_threshold} "
        f"escalates={impact.escalates} rank={margin_priority_rank(impact)} "
        f"(the threshold is recorded and never compared to the delta)"
    )


@case("E2", "E2.2", "A clearing-fund 'deficiency' where posted exceeds requirement",
      "whether a surplus is reported as an under-collateralisation",
      "SPEC-MARGIN-AWARE-BREAKS S9")
def e2_2() -> tuple[str, str]:
    impact = margin_impact_for_clearing_fund_deficiency(
        requirement=D("1"), posted=D("5"), currency="USD", venue="CCP-A"
    )
    negative = impact.delta_amount is not None and impact.delta_amount < 0
    # REFUTED as API misuse. The function renders a state already established
    # upstream by FundingInputs.clearing_fund_sufficient, and its docstring
    # says so. tests/contracts/test_margin_impact.py:529 pins the contract as
    # pure subtraction: "the bridge subtracts; it does not model." The
    # residual is a hygiene item - the model validates direction-vs-disposition
    # but not sign-vs-disposition, and a guard would match its own style.
    return (BY_DESIGN if negative else HELD), (
        f"requirement=1 posted=5 -> {impact.disposition.value} "
        f"delta={impact.delta_amount}. Refuted: a renderer for a deficiency "
        f"already established upstream, pinned by test as pure subtraction. "
        f"Hygiene note: no sign guard, unlike seven other cross-field "
        f"validators on this model."
    )


@case("E2", "E2.3", "An invented venue profile asserting absolute trust",
      "whether a provenance string is evidence or a presence check",
      "AUR-CUSTODY-MARGIN-001 S4")
def e2_3() -> tuple[str, str]:
    from atreides.contracts.margin_profile import (
        DeterminabilityRegime,
        ProfileStatus,
        VenueMarginProfile,
    )

    p = VenueMarginProfile(
        venue_id="ENTIRELY_MADE_UP",
        status=ProfileStatus.POPULATED,
        determinability=DeterminabilityRegime.FULLY_COLLATERALIZED,
        provenance="trust me",
    )
    # REFUTED. A citation string is not machine-verifiable without an external
    # registry, and the module's rule is that an unattributed profile is
    # "indistinguishable from a guess" - attribution is required so a HUMAN
    # reviewer can check it. The presence check is enforced and tested.
    trusted = p.figure_may_be_trusted_absolutely
    return (BY_DESIGN if trusted else HELD), (
        f"provenance={p.provenance!r} -> trusted_absolutely={trusted}. "
        f"Refuted: the rule requires attribution so a reviewer can check it, "
        f"not so the framework can. No software verifies a citation without "
        f"an external registry."
    )


@case("E2", "E2.4", "An unverified emit profile claiming spec verification",
      "whether profile_verified reflects anything the framework can check",
      "the messaging profile discipline")
def e2_4() -> tuple[str, str]:
    forged = DepositoryProfile(name="INVENTED", verified_against_published_spec=True)
    art = emit_instruction_artifact(_instruction(), forged)
    # REFUTED, same class as E2.3. The flag is a caller attestation about
    # documents behind a participant login; emit propagates what it was given
    # and adds nothing. The two real profiles ship UNVERIFIED. Minor
    # consistency nit: unlike DeterminationProfile, this model has no
    # provenance field required alongside the claim.
    return (BY_DESIGN if art.profile_verified else HELD), (
        f"profile={art.profile_name} profile_verified={art.profile_verified}. "
        f"Refuted: an attestation about a document the framework does not "
        f"hold. Nit: no provenance field required alongside the claim."
    )


@case("E2", "E2.5", "A finality class arriving as a plain string from JSON",
      "a deserialised enum must not silently take a more permissive branch",
      "CASH-001 SVII, and the coercion discipline the registries already apply")
def e2_5() -> tuple[str, str]:
    enum_result = project_funding(
        FundingInputs(
            opening_position=D("1000"), obligation=D("10"),
            finality_class=FinalityClass.DETERMINATION_DEPENDENT,
            settlement_offset_seconds=3600,
        )
    )
    string_result = project_funding(
        FundingInputs(
            opening_position=D("1000"), obligation=D("10"),
            finality_class="DETERMINATION_DEPENDENT",  # type: ignore[arg-type]
            settlement_offset_seconds=3600,
        )
    )
    ok = enum_result.disposition is string_result.disposition
    return (HELD if ok else BROKE), (
        f"enum -> {enum_result.disposition.value}; "
        f"raw string -> {string_result.disposition.value}. "
        f"FinalityClass is a StrEnum compared with 'is', so a deserialised "
        f"string misses every branch and lands in the most forgiving one."
    )


# ===========================================================================
# E3 - Multi-agent cascade
# ===========================================================================


@case("E3", "E3.1", "Two agents reacting to each other's output",
      "agent-to-agent messaging, a shared bus, or any concurrency",
      "no doctrine section - no such interaction exists")
def e3_1() -> tuple[str, str]:
    return NO_TARGET, (
        "Exactly one call between components exists: the cockpit instantiates "
        "SettlementOperationsAnalyst and calls .run(). There is no agent-to-"
        "agent messaging, no shared bus, no scheduler and no concurrency "
        "anywhere in the package. A cascade has no medium to propagate through."
    )


@case("E3", "E3.2", "Escalation delivery under load",
      "a router, queue, notifier or acknowledgement path",
      "EscalationRequired carries an escalation_tier")
def e3_2() -> tuple[str, str]:
    return NO_TARGET, (
        "escalation_tier is a label on an object, not a destination. There is "
        "no router, no queue, no notifier and no acknowledgement. An "
        "escalation 'goes to' store.append() - a row in SQLite. Whether a "
        "human ever sees it is outside this framework entirely."
    )


# ===========================================================================
# E4 - Funding viable until finality
# ===========================================================================


@case("E4", "E4.1", "Funded on optimistic flows, short on committed ones",
      "an uncommitted flow must never produce a settles=True projection",
      "CASH-001 SVII")
def e4_1() -> tuple[str, str]:
    p = project_funding(
        FundingInputs(
            opening_position=D("0"), obligation=D("1000000"),
            finality_class=FinalityClass.GROSS_FINAL,
            settlement_offset_seconds=3600,
            window_close_offset_seconds=3600,
            flows=(CashFlow(1800, D("2000000"), "hoped-for", committed=False),),
        )
    )
    ok = not p.settles
    return (HELD if ok else BROKE), (
        f"{p.disposition.value} settles={p.settles} "
        f"projected={p.projected_position_at_settlement} "
        f"optimistic={p.optimistic_position_at_settlement}"
    )


@case("E4", "E4.2", "Ledger-final rail cannot queue",
      "a ledger-final shortfall must fail rather than queue",
      "CASH-001 SIV")
def e4_2() -> tuple[str, str]:
    p = project_funding(
        FundingInputs(
            opening_position=D("0"), obligation=D("100"),
            finality_class=FinalityClass.LEDGER_FINAL,
            settlement_offset_seconds=3600,
            window_close_offset_seconds=14400,
            flows=(CashFlow(7200, D("200"), "later inflow"),),
        )
    )
    ok = p.disposition.value == "will_fail"
    return (HELD if ok else BROKE), f"{p.disposition.value}"


@case("E4", "E4.3", "Negative obligation reads as funded",
      "whether a negative obligation is nonsensical or meaningful",
      "CASH-001 SVII")
def e4_3() -> tuple[str, str]:
    p = project_funding(
        FundingInputs(
            opening_position=D("0"), obligation=D("-500000"),
            finality_class=FinalityClass.GROSS_FINAL,
            settlement_offset_seconds=3600,
        )
    )
    # REFUTED. A negative net obligation is a net RECEIVE, an ordinary state
    # on a netted rail - cns.py models signed positions with is_receive
    # throughout. Owing -500,000 means owing nothing, and FUNDED is correct.
    ok = p.settles and p.shortfall == 0
    return (BY_DESIGN if ok else HELD), (
        f"obligation=-500000 -> {p.disposition.value} shortfall={p.shortfall}. "
        f"Refuted: a negative obligation is a net receive and FUNDED is the "
        f"correct classification."
    )


@case("E4", "E4.4", "NaN in the funding position",
      "whether a corrupt figure fails open or closed",
      "CASH-001 SV.E: callers MUST use absent_gate_decision where the gate "
      "returns no decision")
def e4_4() -> tuple[str, str]:
    try:
        d = evaluate(
            operation=_op(),
            funding=FundingState(D("NaN"), D("1000000"), D("0"), True),
            rails=_rails(),
            ofr_stlfsi4=0.0,
        )
    except Exception as exc:
        # REFUTED as a defect: this fails CLOSED. An exception can never be
        # mistaken for a PROCEED, and the module names the remedy - a caller
        # that gets no decision must use absent_gate_decision() -> HOLD.
        # Distinguish from H1.3, where the input is well formed, doctrine
        # prescribes a decision, and the code asserts an invariant that is
        # false.
        return BY_DESIGN, (
            f"{type(exc).__name__} out of evaluate() before any check ran. "
            f"Fails closed: no path turns this into a PROCEED, and the "
            f"documented remedy is absent_gate_decision() -> HOLD."
        )
    return (HELD if d.decision.value != "PROCEED" else BROKE), (
        f"{d.decision.value}/{d.reason_code.value}"
    )


# ===========================================================================
# E5 - Cross-rail timing and finality mismatch
# ===========================================================================


@case("E5", "E5.1", "Determination pending on the obligation",
      "a pending determination must hold",
      "CASH-AMD-002")
def e5_1() -> tuple[str, str]:
    d = evaluate(
        operation=_op(determination_outcome=DeterminationOutcome.AWAITING_DETERMINATION),
        funding=_funded(),
        rails=_rails(),
        ofr_stlfsi4=0.0,
    )
    ok = d.decision.value == "HOLD" and d.reason_code.value == "DETERMINATION_PENDING"
    return (HELD if ok else BROKE), f"{d.decision.value}/{d.reason_code.value}"


@case("E5", "E5.2", "Qualified obligation on a gross-final rail",
      "the record must carry both finality classes, not collapse them",
      "CASH-AMD-002: money final, entitlement not")
def e5_2() -> tuple[str, str]:
    d = evaluate(
        operation=_op(determination_outcome=DeterminationOutcome.QUALIFIED_UNBOUNDED),
        funding=_funded(),
        rails=_rails(),
        ofr_stlfsi4=0.0,
    )
    ok = (
        d.finality_class is FinalityClass.GROSS_FINAL
        and d.obligation_finality_class is FinalityClass.DETERMINATION_DEPENDENT
    )
    return (HELD if ok else BROKE), (
        f"rail={d.finality_class.value if d.finality_class else None} "
        f"obligation={d.obligation_finality_class.value if d.obligation_finality_class else None} "
        f"decision={d.decision.value}"
    )


@case("E5", "E5.3", "Two determination fields, no cross-check",
      "whether the funding model and the gate can disagree on a determination",
      "CASH-AMD-002; both fields document themselves as consumers of one "
      "upstream classify_determination() call")
def e5_3() -> tuple[str, str]:
    p = project_funding(
        FundingInputs(
            opening_position=D("100000000"), obligation=D("1000000"),
            finality_class=FinalityClass.GROSS_FINAL,
            settlement_offset_seconds=3600,
            determination_outcome=DeterminationOutcome.AWAITING_DETERMINATION,
        )
    )
    d = evaluate(
        operation=_op(determination_outcome=DeterminationOutcome.NOT_APPLICABLE),
        funding=p.to_gate_input(),
        rails=_rails(),
        ofr_stlfsi4=0.0,
    )
    diverged = p.disposition.value == "indeterminate" and d.decision.value == "PROCEED"
    # REFUTED as stated. Both fields consume the SAME upstream classification
    # by documented design, and producing this divergence requires a caller to
    # supply contradictory values to two documented consumers. The real
    # component - that to_gate_input() drops the disposition - is counted once,
    # as H2.3, and must not be counted twice.
    return (BY_DESIGN if diverged else HELD), (
        f"funding={p.disposition.value}, gate={d.decision.value}/"
        f"{d.reason_code.value}. Refuted: consume-don't-re-derive is stated "
        f"doctrine. The genuine part - the disposition dropped at the handoff "
        f"- is counted once as H2.3."
    )


@case("E5", "E5.4", "Securities leg settles for a business date nobody fixed",
      "a message-determined processing date must be named as unestablished",
      "SIGNAL-EXTENDED-HOURS-EQUITIES S7.2")
def e5_4() -> tuple[str, str]:
    from atreides.rails.cns import ProcessingDateRule

    prof = _market(
        processing_date_rule=ProcessingDateRule.SESSION_CLOSURE_MESSAGE,
        session_closure_message="the session-closure message",
    )
    pos = net_positions(
        (("SEC-A", D("1000")),), market_id="XCLR", settlement_date_offset_days=1
    )[0]
    r = settle_net_position(pos, prof, allocated_quantity=D("1000"))
    codes = {b.code.value for b in r.breaks}
    ok = "processing_date_not_established" in codes
    return (HELD if ok else BROKE), f"{r.disposition.value} breaks={sorted(codes)}"


@case("E5", "E5.5", "The clearing corporation allocates more than the position",
      "whether over-allocation is caught or absorbed",
      "EQUITY-001 S3.3: allocated plus residual is what was owed")
def e5_5() -> tuple[str, str]:
    pos = net_positions(
        (("SEC-A", D("100")),), market_id="XCLR", settlement_date_offset_days=1
    )[0]
    r = settle_net_position(pos, _market(), allocated_quantity=D("500"))
    residual = r.residual.quantity if r.residual else D(0)
    conserved = r.allocated_quantity + residual == pos.quantity
    # REFUTED by an existing property test. tests/test_properties.py:515 draws
    # quantity and allocated INDEPENDENTLY, so over-allocation is generated on
    # every deep run, and the asserted invariant is exactly
    # allocated + residual == owed - which a negative residual satisfies. The
    # conservation law is the doctrine. Separately, a CCP cannot allocate more
    # than the net position, so the input is not producible.
    return (BY_DESIGN if conserved else BROKE), (
        f"position=100 allocated=500 -> {r.disposition.value} "
        f"residual={residual} conservation_holds={conserved}. Refuted: a "
        f"Hypothesis property already generates this and asserts the "
        f"conservation law it satisfies."
    )


@case("E5", "E5.6", "A flat position with a reported allocation against it",
      "a movement reported against a netted-out position must be surfaced",
      "EQUITY-001 S2")
def e5_6() -> tuple[str, str]:
    pos = net_positions(
        (("SEC-A", D("100")), ("SEC-A", D("-100"))),
        market_id="XCLR",
        settlement_date_offset_days=1,
    )[0]
    r = settle_net_position(pos, _market(), allocated_quantity=D("50"))
    ok = bool(r.breaks) or r.disposition.value != "flat"
    return (HELD if ok else BROKE), (
        f"net=0 allocated=50 -> {r.disposition.value} "
        f"allocated_recorded={r.allocated_quantity} completed={r.completed} "
        f"breaks={len(r.breaks)}"
    )


# ===========================================================================
# E6 - Autonomous agent plus final settlement
# ===========================================================================


@case("E6", "E6.1", "Anything in the package can transmit an instruction",
      "the no-submission constraint must be structural",
      "the permanent constraint: Atreides never submits")
def e6_1() -> tuple[str, str]:
    import importlib
    import pkgutil

    import atreides

    forbidden = {
        "socket", "requests", "httpx", "urllib", "http", "smtplib",
        "subprocess", "asyncio", "ftplib", "paramiko",
    }
    found: list[str] = []
    for mod in pkgutil.walk_packages(atreides.__path__, "atreides."):
        try:
            m = importlib.import_module(mod.name)
        except Exception:
            continue
        src = getattr(m, "__file__", None)
        if not src:
            continue
        text = pathlib.Path(src).read_text(encoding="utf-8")
        for token in forbidden:
            if f"import {token}" in text:
                found.append(f"{mod.name}:{token}")
    ok = not found
    return (HELD if ok else BROKE), (
        f"transport imports across the whole package: {found or 'none'}. "
        f"The constraint is enforced by absence of capability."
    )


@case("E6", "E6.2", "A submission artifact constructed directly",
      "is_submission must be unconstructible as True",
      "emit.py claims parity with the cockpit's type-layer control")
def e6_2() -> tuple[str, str]:
    from atreides.messaging.emit import InstructionArtifact

    try:
        art = InstructionArtifact(b"", b"", "m", "p", True, None, True)  # type: ignore[arg-type]
        constructed = art.is_submission
    except Exception as exc:
        return HELD, f"refused at construction: {type(exc).__name__}"
    return BROKE, (
        f"InstructionArtifact(is_submission={constructed}) constructed. It is a "
        f"plain frozen dataclass, so Literal[False] is a static annotation "
        f"only. The cockpit's InstructionPackage is a pydantic model where the "
        f"same annotation IS enforced; the two are not at parity, and emit.py "
        f"claims they are."
    )


@case("E6", "E6.3", "A material-magnitude operation must not emit a package",
      "material magnitude routes to quorum, which is unavailable",
      "AUR-COCKPIT-001; CASH-001 SV.B check 2")
def e6_3() -> tuple[str, str]:
    cockpit = ClearingCockpit()
    t = cockpit.capture_tasking(
        regime=PortalRegime.CCP,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="CP-1",
        settlement_date=datetime(2026, 8, 19, tzinfo=UTC),
        authority_id="OP-1",
        net_delivery_quantity=D("1000"),
        net_payment_amount=D("999000000000"),
        ficc_published_net_delivery=D("1000"),
    )
    gate = cockpit.run_validation_gates(t)
    pkg = cockpit.emit_instruction_package(t, gate)
    ok = pkg.disposition.value != "emit_for_human_entry"
    return (HELD if ok else BROKE), f"disposition={pkg.disposition.value}"


@case("E6", "E6.4", "Presence-only quorum validation",
      "whether the architectural validator inspects the ceremony it requires",
      "the inherent-safety axiom: such an operation carries a quorum authority")
def e6_4() -> tuple[str, str]:
    pool = tuple(
        SigningAuthority(
            authority_id=f"A{i}", identity_id=f"I{i}",
            organizational_unit=f"U{i}", jurisdiction=f"J{i}",
            signing_system=f"S{i}",
        )
        for i in range(5)
    )
    q = QuorumAuthority(
        independence_requirements=frozenset(),
        signing_pool=pool,
    )
    unstarted = (
        q.ceremony_state is CeremonyState.PENDING and not q.collected_signatures
    )
    # Narrowed after refutation. A PENDING ceremony with zero signatures is
    # the correct representation of a ceremony that has not started, and the
    # model DOES enforce exactly N signatures for COMPLETED. What the
    # substrate-not-execution defence does not cover: the architectural
    # validator in contracts/operations/base.py requires the PRESENCE of a
    # quorum record on an inherent-safety operation and never inspects
    # ceremony_state or the signature count, so an unstarted ceremony
    # satisfies the axiom.
    return (BROKE if unstarted else HELD), (
        f"state={q.ceremony_state.value} "
        f"signatures={len(q.collected_signatures)}. Narrowed: the ceremony "
        f"model is sound and enforces exactly N signatures for COMPLETED. The "
        f"finding is in the architectural validator, which accepts the "
        f"presence of an unstarted ceremony as satisfying the requirement."
    )


@case("E6", "E6.5", "A completed ceremony with all signatures at the same instant",
      "whether temporal independence is enforced when requested",
      "the quorum contract's TEMPORAL requirement")
def e6_5() -> tuple[str, str]:
    from atreides.contracts.quorum import Signature

    pool = tuple(
        SigningAuthority(
            authority_id=f"A{i}", identity_id=f"I{i}",
            organizational_unit=f"U{i}", jurisdiction=f"J{i}",
            signing_system=f"S{i}",
        )
        for i in range(5)
    )
    same = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    try:
        q = QuorumAuthority(
            independence_requirements=frozenset({IndependenceRequirement.TEMPORAL}),
            signing_pool=pool,
            collected_signatures=tuple(
                Signature(authority_id=f"A{i}", signed_at=same) for i in range(3)
            ),
            ceremony_state=CeremonyState.COMPLETED,
        )
    except Exception as exc:
        return HELD, f"refused: {type(exc).__name__}"
    # REFUTED, and this is the clearest refutation in the set. The
    # non-enforcement is stated in the module docstring, on the field, in the
    # validator's own docstring, twice in FOLLOW-UPS, and asserted by a test
    # named test_temporal_requirement_carried_but_not_enforced_at_contracts.
    return BY_DESIGN, (
        f"COMPLETED with {len(q.collected_signatures)} signatures at one "
        f"instant while TEMPORAL was requested. Refuted: a test asserts this "
        f"by name and four separate docstrings state that interval "
        f"enforcement is a ceremony-execution concern the contracts layer "
        f"does not take on."
    )


# ===========================================================================
# E7 - Governance and lineage failure
# ===========================================================================


@case("E7", "E7.1", "The gate is unavailable",
      "no decision must default to release",
      "'the absence of evidence is a state with a name'")
def e7_1() -> tuple[str, str]:
    from atreides.rails.cato_f import absent_gate_decision

    d = absent_gate_decision("gate offline during incident")
    ok = d.decision.value == "HOLD" and not d.proceeds
    return (HELD if ok else BROKE), f"{d.decision.value}/{d.reason_code.value}"


@case("E7", "E7.2", "A lineage hash is never re-verified on replay",
      "whether a state hash is checked against the state it claims to cover",
      "the DSOR lineage discipline")
def e7_2() -> tuple[str, str]:
    stub = DSORLineageStub(
        authority_tier=CAOMTier.T1,
        authority_id="OP-1",
        initiated_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
        pre_operation_state_hash="a" * 64,
    )
    format_only = len(stub.pre_operation_state_hash) == 64
    # CORRECTED. An earlier version of this case claimed the hash "is never
    # computed anywhere in the package." That was false, and the source
    # refutes it in thirty seconds: CockpitTasking.pre_operation_state_hash()
    # is a real SHA-256 over the deterministic JSON of the captured tasking,
    # bound into the lineage stub by run_validation_gates. What is true is
    # narrower - the contracts-layer stub validates format only, and no code
    # re-verifies a hash on replay - and the repository already discloses that
    # hash-chaining is roadmap and no tamper-evidence is claimed.
    return (BY_DESIGN if format_only else HELD), (
        "a hand-written 64-hex string is accepted by the contracts stub. "
        "CORRECTED: the hash IS computed and bound in the cockpit. What "
        "remains is that it is never re-verified on replay, which the repo "
        "discloses as roadmap rather than claims as a control."
    )


@case("E7", "E7.3", "A correction pointing at a record that does not exist",
      "a correction chain must resolve",
      "the DSOR append-only claim")
def e7_3() -> tuple[str, str]:
    from atreides.dsor.store import DSORStore

    store = DSORStore(":memory:")
    try:
        rec = store.append(_timeline(), correction_of=uuid.uuid4())
    except Exception as exc:
        return HELD, f"refused: {type(exc).__name__}: {exc}"
    return BROKE, (
        f"correction_of={rec.correction_of} accepted with no such record in "
        f"the store. There is no foreign key and no existence check, so a "
        f"correction chain can dangle or cycle, and nothing in the module "
        f"orders or resolves a chain."
    )


@case("E7", "E7.4", "A decision-of-record backdated by a decade",
      "whether a record's timestamp is constrained",
      "the DSOR append-only claim")
def e7_4() -> tuple[str, str]:
    from atreides.dsor.store import DSORStore

    store = DSORStore(":memory:")
    old = datetime(2016, 1, 1, tzinfo=UTC)
    try:
        rec = store.append(_timeline(), dtg=old)
    except Exception as exc:
        return HELD, f"refused: {type(exc).__name__}"
    # REFUTED: disclosed. docs/SCENARIO-DSOR-LINEAGE-MISMATCH.md states that
    # the DSOR is append-only by construction, that hash-chaining is roadmap,
    # and that NO TAMPER-EVIDENCE IS CLAIMED. Backdating and ordering are
    # precisely what a hash chain addresses. dtg defaults to now(UTC); the
    # parameter exists for deterministic replay.
    return BY_DESIGN, (
        f"accepted with dtg={rec.dtg.isoformat()}. Refuted: the repository "
        f"states that no tamper-evidence is claimed and that hash-chaining is "
        f"roadmap. An absence that is disclosed is not a finding."
    )


@case("E7", "E7.6", "Unlimited corrections against one operation",
      "what 'append-only' is claimed to mean here",
      "the DSOR append-only claim")
def e7_6() -> tuple[str, str]:
    from atreides.dsor.store import DSORStore

    store = DSORStore(":memory:")
    op_id = uuid.uuid4()
    first = store.append(_timeline(op_id))
    chain = [first.record_id]
    try:
        for _ in range(20):
            r = store.append(_timeline(op_id), correction_of=chain[-1])
            chain.append(r.record_id)
    except Exception as exc:
        return HELD, f"refused after {len(chain)} corrections: {type(exc).__name__}"
    original_intact = store.replay(first.record_id) is not None
    # REFUTED. The store's own docstring specifies this as the design:
    # corrections are exempt from the unique index "so the correction chain
    # can accumulate", and two tests assert corrections succeed with the
    # original untouched. Append-only means the original is never overwritten,
    # which is what it means everywhere in records management.
    return (BY_DESIGN if original_intact else BROKE), (
        f"{len(chain) - 1} corrections accepted; the original still replays "
        f"intact={original_intact}. Refuted: the module documents the "
        f"correction chain as the design and two tests assert it."
    )


@case("E7", "E7.5", "The gate decision has no supported type in the store",
      "whether the decision of record can carry the cash gate's own output",
      "cato_f.py:15-32 architectural contract: PURE, NO I/O")
def e7_5() -> tuple[str, str]:
    from atreides.dsor.record import AureonOutput

    d = evaluate(operation=_op(), funding=_funded(), rails=_rails(), ofr_stlfsi4=0.0)
    gate_persistable = "CatoF" in str(AureonOutput)
    # REFUTED as stated: purity is an explicit architectural contract and
    # persistence is the caller's by design - that purity is what makes
    # checks_evaluated a replay record in the first place. What survives is a
    # narrower integration gap: the AureonOutput union has no member capable
    # of carrying a gate decision, so there is no supported TYPE for
    # persisting one even where a caller wants to.
    return (BROKE if not gate_persistable else HELD), (
        f"evaluate() returned {d.decision.value} and wrote nothing, which is "
        f"the stated contract. Narrowed: the AureonOutput union has no member "
        f"that can carry a CatoFDecision, so the cash gate's own output has "
        f"no supported type in the decision of record. Integration gap in the "
        f"store's union, not a defect in the gate."
    )



# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_case(c: Case) -> dict[str, object]:
    try:
        verdict, observed = c.fn()
    except Exception as exc:
        verdict, observed = CRASHED, f"probe raised {type(exc).__name__}: {exc}"
    return {
        "family": c.family,
        "case_id": c.case_id,
        "title": c.title,
        "attacks": c.attacks,
        "doctrine": c.doctrine,
        "verdict": verdict,
        "observed": observed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("families", nargs="*", help="family codes, e.g. H1 E4")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    if args.list:
        for code, name in FAMILIES.items():
            n = sum(1 for c in CASES if c.family == code)
            print(f"  {code}  {name}  ({n} cases)")
        return 0

    selected = [c for c in CASES if not args.families or c.family in args.families]
    results = [run_case(c) for c in selected]

    if args.json:
        print(json.dumps({"results": results}, indent=2, sort_keys=True))
    else:
        current = None
        for r in results:
            if r["family"] != current:
                current = r["family"]
                print(f"\n=== {current}  {FAMILIES[str(current)]}")
                print("=" * 74)
            print(f"\n  [{r['verdict']:<9}] {r['case_id']}  {r['title']}")
            print(f"             attacks: {r['attacks']}")
            print(f"             doctrine: {r['doctrine']}")
            for line in _wrap(str(r["observed"]), 62):
                print(f"             {line}")

        print("\n" + "=" * 74)
        tally: dict[str, int] = {}
        for r in results:
            tally[str(r["verdict"])] = tally.get(str(r["verdict"]), 0) + 1
        for v in (HELD, BY_DESIGN, BROKE, CRASHED, NO_TARGET):
            print(f"  {v:<10} {tally.get(v, 0)}")
        print(f"  {'TOTAL':<10} {len(results)}")
        print(
            "\n  NO_TARGET is not a pass. It means nothing in this repository "
            "\n  implements the thing the case attacks."
        )

    broke = sum(1 for r in results if r["verdict"] in {BROKE, CRASHED})
    if args.strict and broke:
        return 1
    return 0


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


if __name__ == "__main__":
    sys.exit(main())
