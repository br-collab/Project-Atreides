# SCF-1 firm at volume

**SYNTHETIC LOAD LEVEL: no claim about any real firm.**

Tier `small`: 200 accounts, 20 issues, 1,000 executions per day. All close invariants green: `True`.

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
- possession_or_control: `4` PASS, `1` HOLD; independently required: `PASS / HOLD / PASS / PASS / PASS`; reasons: `loaned[SYN-SCF1-ISSUE-0000]; SYN-SCF1-ISSUE-0000: 100 fully paid or excess margin securities are not in possession or control`

## Not claimed

- regulatory approval
- production readiness
- clearing-agency membership
- real customer assets
- real firm, account or security identifiers
