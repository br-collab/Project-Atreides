# MVP-5C synthetic golden path closure

This pack contains one declared-synthetic natural-person account and one declared-synthetic United States equity. It records the ordered cause chain from application through the daily close. No event was submitted to a venue, depository, bank, or regulator.

Evidence digest: `sha256:83d97462b0971ed1664bcf4bb15a960b2ca858c7c7d5bf95a0e7e1f2576fd0f3`

| Figure | Prior pack | Current pack | Reason |
| --- | ---: | ---: | --- |
| Closing free cash | 10000.00 | 9000.00 | Cash-account purchase now reduces free cash |
| Closing margin balance | Combined with cash | 0.00 | Cash and margin are reported separately |
| Closing shares | 10 | 10 | Position posting is unchanged |

Every clean-run invariant in `evidence-pack.json` is true.
