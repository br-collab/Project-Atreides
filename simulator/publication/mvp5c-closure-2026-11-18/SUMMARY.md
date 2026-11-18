# MVP-5C synthetic golden path closure

This pack contains one declared-synthetic natural-person account and one declared-synthetic United States equity. It records the ordered cause chain from application through the daily close. No event was submitted to a venue, depository, bank, or regulator.

Evidence digest: `sha256:1baf2d7a07fe709648154753f6852be255c379913774b122530248dad9b49443`

| Figure | Prior pack | Current pack | Reason |
| --- | ---: | ---: | --- |
| Closing free cash | 10000.00 | 9000.00 | Cash-account purchase now reduces free cash |
| Closing margin balance | Combined with cash | 0.00 | Cash and margin are reported separately |
| Closing shares | 10 | 10 | Position posting is unchanged |

Every clean-run invariant in `evidence-pack.json` is true.
