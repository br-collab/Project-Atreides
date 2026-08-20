"""The stress probe must keep running, and its verdicts must not drift silently.

The probe's value is that it is an inventory of what this framework does under
attack. An inventory nobody reruns is a snapshot, and a snapshot of a codebase
is wrong within a month.

Two things are pinned here and they pin opposite risks:

- **Every case must be able to return more than one verdict.** A case that
  returns a fixed answer is an assertion about the framework, not a test of
  it. An earlier version of the probe had five such cases and they were the
  first thing an adversarial reviewer found.
- **The finding count is pinned.** If somebody fixes a defect, this test
  fails and the fix has to be recorded. If somebody introduces one, it fails
  too. Either way the drift surfaces in review rather than in a report
  written three months later against a number that has moved.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import stress_probe  # noqa: E402

#: Verdicts as of the current run. Update deliberately, with the reason,
#: never to make the suite green.
#:
#: 19 Aug 2026: the three HIGH findings were fixed, and this test caught the
#: change - which is what it is for. H1.3 CRASHED -> HELD (check 6 now tests
#: capacity, and the ladder returns None rather than asserting). H5.1
#: BROKE -> HELD (a non-finite stress reading is named and held). H2.3
#: BROKE -> HELD (the funding model's refusal now travels with the numbers).
#: E5.3 BY_DESIGN -> HELD, unplanned: propagating the disposition also closed
#: the determination divergence, because AWAITING_DETERMINATION produces an
#: INDETERMINATE disposition. H5.4 HELD -> HELD with a different expectation:
#: +inf is now named unusable rather than escalated as observed stress.
#:
#: 19 Aug 2026, later: the four MEDIUM findings closed too. H7.4, E5.6,
#: E2.1 and E7.3 all moved BROKE -> HELD. Eight findings remain, all LOW.
#:
#: 19 Aug 2026, Tier A: three families that had nothing to attack now do.
#: H5.3 (market-data staleness), H4.1 (counterparty standing) and E3.2
#: (escalation delivery) moved NO_TARGET -> HELD. NO_TARGET falls from
#: nine to six, and that number only moves by building something.
EXPECTED = {
    "HELD": 31,
    "BY_DESIGN": 15,
    "BROKE": 8,
    "NO_TARGET": 6,
}


@pytest.fixture(scope="module")
def results() -> list[dict[str, object]]:
    return [stress_probe.run_case(c) for c in stress_probe.CASES]


def test_every_case_runs(results) -> None:
    assert len(results) == sum(EXPECTED.values())
    for r in results:
        assert r["verdict"] in {
            stress_probe.HELD,
            stress_probe.BY_DESIGN,
            stress_probe.BROKE,
            stress_probe.CRASHED,
            stress_probe.NO_TARGET,
        }


def test_every_case_is_deterministic() -> None:
    """A probe whose verdicts move between runs cannot support a finding."""
    first = [stress_probe.run_case(c) for c in stress_probe.CASES]
    second = [stress_probe.run_case(c) for c in stress_probe.CASES]
    assert [r["verdict"] for r in first] == [r["verdict"] for r in second]


def test_the_verdict_tally_has_not_drifted(results) -> None:
    tally: dict[str, int] = {}
    for r in results:
        tally[str(r["verdict"])] = tally.get(str(r["verdict"]), 0) + 1
    assert tally == EXPECTED, (
        f"stress verdicts moved: {tally} != {EXPECTED}. If a defect was fixed, "
        f"update EXPECTED and say so in the commit. If one appeared, that is "
        f"the point of this file."
    )


def test_every_case_states_what_it_attacks_and_against_what(results) -> None:
    """A finding with no invariant behind it is an opinion."""
    for r in results:
        assert str(r["attacks"]).strip()
        assert str(r["doctrine"]).strip()
        assert str(r["observed"]).strip()


def test_no_case_returns_a_fixed_verdict() -> None:
    """The defect that nearly discredited the first run of this probe.

    A case whose only ``return`` is unconditional cannot report that the
    framework held, so it tests nothing. Cases where the alternative verdict
    is reached through an ``except`` branch are legitimate and are recognised
    here.
    """
    src = (REPO / "tools" / "stress_probe.py").read_text(encoding="utf-8")
    bodies = re.split(r"^@case\(", src, flags=re.M)[1:]
    offenders = []
    for body in bodies:
        case_id = re.search(r'"([HE]\d\.\d)"', body)
        verdicts = re.findall(r"return (HELD|BY_DESIGN|BROKE|CRASHED|NO_TARGET)", body)
        conditional = "if " in body and "return (" in body
        has_except_path = "except" in body
        if len(set(verdicts)) <= 1 and not conditional and not has_except_path:
            offenders.append(case_id.group(1) if case_id else "?")
    # NO_TARGET cases are the deliberate exception: they assert that nothing
    # in the repository implements the thing attacked, which is a fact about
    # the codebase rather than a measurement of its behaviour.
    offenders = [
        o for o in offenders
        if f'"{o}"' not in "".join(
            b for b in bodies if "return NO_TARGET" in b
        )
    ]
    assert not offenders, f"cases with a fixed verdict and no branch: {offenders}"


def test_no_target_is_never_counted_as_a_pass(results) -> None:
    """The scope-honesty rule the whole report rests on."""
    no_target = [r for r in results if r["verdict"] == stress_probe.NO_TARGET]
    assert no_target, "the probe claims coverage it should not have"
    for r in no_target:
        text = str(r["observed"]).lower()
        assert any(
            phrase in text
            for phrase in ("no ", "not ", "nothing", "absent", "does not")
        ), f"{r['case_id']} reports NO_TARGET without saying what is missing"
