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

## MVP-1B old and new comparison

| Measure | MVP-1 publication | MVP-1B publication | Reason |
| --- | --- | --- | --- |
| DTC source | derived street movements | seeded depository plus CNS settlement outcomes and declared instructions | remove book-derived street facts |
| FTR source | book-derived FTR movements | CNS open-fail statement keyed by fail ID | preserve independent quantity and age evidence |
| Stock-loan source | depository categories | declared loan-contract register | separate custody from lending evidence |
| Reconciliation calendar | configured intent | observed completed, failed or not-run status | prevent a configured job from being reported as run |
| Fail aging | net issue-level balance | per-fail identity and opening date | prevent a reopened fail from inheriting an older fail's age |

## Firm section

- Executions: 5,000
- Fails by age: `{'0': 40, '1': 20, '2': 20, '3': 20}`
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
