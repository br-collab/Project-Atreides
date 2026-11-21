# PS-1B true reconciliation rows

This pack contains one declared-synthetic natural-person account and one declared-synthetic United States equity. It records the ordered cause chain from application through the settlement date close. No event was submitted to a venue, depository, bank, or regulator.

| Figure | Prior pack | Current pack | Reason |
| --- | ---: | ---: | --- |
| Reconciliation rows | Six constant RAN rows | Six control result rows | Rows now carry each control's status, break count and sources read |
| Closing free cash | 9000.00 | 9000.00 | Customer economics are unchanged |
| Closing shares | 10 | 10 | Customer economics are unchanged |
| Settlement status | SETTLED | SETTLED | Dated posting is unchanged |
| Cost basis | 1000.00 | 1000.00 | Journal-replayed lots are unchanged |
| Unrealized gain or loss | 0.00 | 0.00 | Synthetic closing price is unchanged |

The trade-date statement reports the same cash and shares as `UNSETTLED`; the settlement-date statement reports them as `SETTLED`. All six reconciliation calendar rows report `RAN` with zero breaks, and every clean-run invariant in `evidence-pack.json` is true.
