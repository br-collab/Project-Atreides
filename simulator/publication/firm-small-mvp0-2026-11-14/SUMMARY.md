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

## Firm section

- Executions: 5,000
- Fails by age: `{'0': 40, '1': 20, '2': 20, '3': 20}`
- Breaks by owner: `{}`
- I11 position roll-forward: `True`
- I12 idempotent replay: `True`

## Synthetic net capital comparison

These are synthetic simulator outputs, not actual regulatory filings or real firm figures.

| Close | Prior synthetic net capital | MVP-0 synthetic net capital | Prior synthetic haircut | MVP-0 synthetic haircut |
| --- | ---: | ---: | ---: | ---: |
| 2027-01-04 | 338893750.0000 | 999970911.3250 | 661106250.0000 | 29088.6750 |
| 2027-01-05 | 310285381.6975 | 999969652.0450 | 689714618.3025 | 30347.9550 |
| 2027-01-06 | 66083832.9355 | 999958905.9250 | 933916167.0645 | 41094.0750 |
| 2027-01-07 | 128533448.1955 | 999961653.1750 | 871466551.8045 | 38346.8250 |
| 2027-01-08 | 59332470.3190 | 999958607.2750 | 940667529.6810 | 41392.7250 |

The first-close synthetic proprietary market value is 193924.50, approximately 0.0194%
of the declared 1000000000 synthetic net worth.

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
