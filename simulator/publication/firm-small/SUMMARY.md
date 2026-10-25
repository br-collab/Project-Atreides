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

- reserve: `5` PASS, `0` HOLD; reasons: `none`
- pab_reserve: `5` PASS, `0` HOLD; reasons: `none`
- net_capital: `5` PASS, `0` HOLD; reasons: `none`
- possession_or_control: `0` PASS, `5` HOLD; reasons: `excess_margin[SYN-SCF1-ISSUE-0000]; excess_margin[SYN-SCF1-ISSUE-0001]; excess_margin[SYN-SCF1-ISSUE-0002]; excess_margin[SYN-SCF1-ISSUE-0003]; excess_margin[SYN-SCF1-ISSUE-0004]; excess_margin[SYN-SCF1-ISSUE-0005]; excess_margin[SYN-SCF1-ISSUE-0006]; excess_margin[SYN-SCF1-ISSUE-0007]; excess_margin[SYN-SCF1-ISSUE-0008]; excess_margin[SYN-SCF1-ISSUE-0009]; excess_margin[SYN-SCF1-ISSUE-0010]; excess_margin[SYN-SCF1-ISSUE-0011]; excess_margin[SYN-SCF1-ISSUE-0012]; excess_margin[SYN-SCF1-ISSUE-0013]; excess_margin[SYN-SCF1-ISSUE-0014]; excess_margin[SYN-SCF1-ISSUE-0015]; excess_margin[SYN-SCF1-ISSUE-0016]; excess_margin[SYN-SCF1-ISSUE-0017]; excess_margin[SYN-SCF1-ISSUE-0018]; excess_margin[SYN-SCF1-ISSUE-0019] | excess_margin[SYN-SCF1-ISSUE-0000]; excess_margin[SYN-SCF1-ISSUE-0001]; excess_margin[SYN-SCF1-ISSUE-0002]; excess_margin[SYN-SCF1-ISSUE-0003]; excess_margin[SYN-SCF1-ISSUE-0004]; excess_margin[SYN-SCF1-ISSUE-0005]; excess_margin[SYN-SCF1-ISSUE-0006]; excess_margin[SYN-SCF1-ISSUE-0007]; excess_margin[SYN-SCF1-ISSUE-0008]; excess_margin[SYN-SCF1-ISSUE-0009]; excess_margin[SYN-SCF1-ISSUE-0010]; excess_margin[SYN-SCF1-ISSUE-0011]; excess_margin[SYN-SCF1-ISSUE-0012]; excess_margin[SYN-SCF1-ISSUE-0013]; excess_margin[SYN-SCF1-ISSUE-0014]; excess_margin[SYN-SCF1-ISSUE-0015]; excess_margin[SYN-SCF1-ISSUE-0016]; excess_margin[SYN-SCF1-ISSUE-0017]; excess_margin[SYN-SCF1-ISSUE-0018]; excess_margin[SYN-SCF1-ISSUE-0019] | excess_margin[SYN-SCF1-ISSUE-0000]; excess_margin[SYN-SCF1-ISSUE-0001]; excess_margin[SYN-SCF1-ISSUE-0002]; excess_margin[SYN-SCF1-ISSUE-0003]; excess_margin[SYN-SCF1-ISSUE-0004]; excess_margin[SYN-SCF1-ISSUE-0005]; excess_margin[SYN-SCF1-ISSUE-0006]; excess_margin[SYN-SCF1-ISSUE-0007]; excess_margin[SYN-SCF1-ISSUE-0008]; excess_margin[SYN-SCF1-ISSUE-0009]; excess_margin[SYN-SCF1-ISSUE-0010]; excess_margin[SYN-SCF1-ISSUE-0011]; excess_margin[SYN-SCF1-ISSUE-0012]; excess_margin[SYN-SCF1-ISSUE-0013]; excess_margin[SYN-SCF1-ISSUE-0014]; excess_margin[SYN-SCF1-ISSUE-0015]; excess_margin[SYN-SCF1-ISSUE-0016]; excess_margin[SYN-SCF1-ISSUE-0017]; excess_margin[SYN-SCF1-ISSUE-0018]; excess_margin[SYN-SCF1-ISSUE-0019] | excess_margin[SYN-SCF1-ISSUE-0000]; excess_margin[SYN-SCF1-ISSUE-0001]; excess_margin[SYN-SCF1-ISSUE-0002]; excess_margin[SYN-SCF1-ISSUE-0003]; excess_margin[SYN-SCF1-ISSUE-0004]; excess_margin[SYN-SCF1-ISSUE-0005]; excess_margin[SYN-SCF1-ISSUE-0006]; excess_margin[SYN-SCF1-ISSUE-0007]; excess_margin[SYN-SCF1-ISSUE-0008]; excess_margin[SYN-SCF1-ISSUE-0009]; excess_margin[SYN-SCF1-ISSUE-0010]; excess_margin[SYN-SCF1-ISSUE-0011]; excess_margin[SYN-SCF1-ISSUE-0012]; excess_margin[SYN-SCF1-ISSUE-0013]; excess_margin[SYN-SCF1-ISSUE-0014]; excess_margin[SYN-SCF1-ISSUE-0015]; excess_margin[SYN-SCF1-ISSUE-0016]; excess_margin[SYN-SCF1-ISSUE-0017]; excess_margin[SYN-SCF1-ISSUE-0018]; excess_margin[SYN-SCF1-ISSUE-0019] | excess_margin[SYN-SCF1-ISSUE-0000]; excess_margin[SYN-SCF1-ISSUE-0001]; excess_margin[SYN-SCF1-ISSUE-0002]; excess_margin[SYN-SCF1-ISSUE-0003]; excess_margin[SYN-SCF1-ISSUE-0004]; excess_margin[SYN-SCF1-ISSUE-0005]; excess_margin[SYN-SCF1-ISSUE-0006]; excess_margin[SYN-SCF1-ISSUE-0007]; excess_margin[SYN-SCF1-ISSUE-0008]; excess_margin[SYN-SCF1-ISSUE-0009]; excess_margin[SYN-SCF1-ISSUE-0010]; excess_margin[SYN-SCF1-ISSUE-0011]; excess_margin[SYN-SCF1-ISSUE-0012]; excess_margin[SYN-SCF1-ISSUE-0013]; excess_margin[SYN-SCF1-ISSUE-0014]; excess_margin[SYN-SCF1-ISSUE-0015]; excess_margin[SYN-SCF1-ISSUE-0016]; excess_margin[SYN-SCF1-ISSUE-0017]; excess_margin[SYN-SCF1-ISSUE-0018]; excess_margin[SYN-SCF1-ISSUE-0019]`

## Not claimed

- regulatory approval
- production readiness
- clearing-agency membership
- real customer assets
- real firm, account or security identifiers
