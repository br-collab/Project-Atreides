# SCF-1 firm at volume

**SYNTHETIC LOAD LEVEL: no claim about any real firm.**

synthetic mode: signatures authenticate within one run only

Tier `small`: 200 accounts, 20 issues, 1,000 executions per day. All close invariants green: `True`.

## Publication change reasons

- MVP-0 moves opening customer holdings out of the proprietary book
- MVP-0 declares a small synthetic proprietary book in calibration
- N2 restricts net capital haircut inputs to firm proprietary positions
- N3 includes PAB free credits in the PAB reserve computation
- N4 removes fails to deliver from the Rule 15c3-3(d)(2) control location
- N5 declares stock-loan holdings as loaned
- MVP-1 replaces the self-comparison with an independent street statement
- MVP-1 reports the declared reconciliation calendar at every close
- MVP-1 nets fail-to-receive and stock-loan lifecycle balances
- MVP-1B sources DTC, CNS fails and the stock-loan register independently
- MVP-1B preserves fail identity through posting, projection and aging
- MVP-1B records observed reconciliation completion and source failures
- MVP-1C fails I3 closed on failed or missing observed reconciliation
- MVP-1C carries CNS residuals as non-growing fail lots
- MVP-1C sizes recall from the independent loan register
- MVP-2 settles the oldest carried fail lot before newer lots
- MVP-2 reconciles the production run through independent source readers
- MVP-2 ties regulatory-report figures to every firm-at-volume close
- MVP-2 creates owned synthetic drafts for fired early-warning indicators

## MVP-1C old and new comparison

| Measure | MVP-1B publication | MVP-1C publication | Reason |
| --- | --- | --- | --- |
| Forced reconciliation failure, I3 | true | false | fail closed on observed failure |
| Fail ID growth cases in five days | 40 | 0 | split residual excess into a new lot |
| Fail ID direction changes in five days | 32 | 0 | close the old lot before a sign change |
| Recall sizing source | books entry scan | loan-register open balance | remove the circular recall input |

## MVP-2 old and new comparison

| Measure | MVP-1C firm publication | MVP-2 firm publication | Reason |
| --- | --- | --- | --- |
| Firm closes with I13 FOCUS tie-out | 0 of 5 | 5 of 5 | run the tie-out on each real firm-at-volume close |
| Firm closes with I16 early-warning workflow control | 0 of 5 | 5 of 5 | require an owned draft for every fired indicator |
| Customer accounts in the FOCUS source book | 0 | 200 | replace the one-line capital book with the firm book |
| Journal entries read at the five closes | 1 per isolated FOCUS close | 79, 168, 269, 373, 468 | tie book lines to engine results at the published closes |
| Control-location identifiers | `DTC`, `BANK` | `15c3-3.control.*` | use the identifiers projected holdings actually carry |

## Firm section

- Executions: 5,000
- Fails by age: `{'0': 64, '1': 20, '2': 13, '3': 3}`
- Breaks by owner: `{}`
- I11 position roll-forward: `True`
- I12 idempotent replay: `True`

## Reserve protection

- reserve: `5` PASS, `0` HOLD; independently required: `PASS / PASS / PASS / PASS / PASS`; reasons: `none`
- pab_reserve: `5` PASS, `0` HOLD; independently required: `PASS / PASS / PASS / PASS / PASS`; reasons: `none`
- net_capital: `5` PASS, `0` HOLD; independently required: `PASS / PASS / PASS / PASS / PASS`; reasons: `none`
- possession_or_control: `4` PASS, `1` HOLD; independently required: `PASS / HOLD / PASS / PASS / PASS`; reasons: `SYN-SCF1-ISSUE-0000: 100 fully paid or excess margin securities are not in possession or control`

## Not claimed

- regulatory approval
- production readiness
- clearing-agency membership
- real customer assets
- real firm, account or security identifiers
