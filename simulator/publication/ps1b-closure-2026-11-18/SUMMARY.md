# PS-1B closure

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

## Tax-lot rules

FIFO is applied under 26 CFR 1.1012-1(c)(1)(i), and specific identification must be recorded no later than the settlement deadline under 26 CFR 1.1012-1(c)(8). Broker basis reporting is cited to 26 CFR 1.6045-1(d)(2)(i)(A). Wash-sale adjustment remains `TO_VERIFY`: the journal does not carry the verified CUSIP or other covered-security identifier required to apply 26 CFR 1.6045-1(d)(6)(iii) deterministically.

## Account treatment

The evidence pack includes a row for each PS-1 account type. Each is marked `TO_VERIFY_AGAINST_PRIMARY_TEXT` because the pinned 17 CFR 240.15c3-3 and 240.15c3-3a text does not settle the internal placement.
