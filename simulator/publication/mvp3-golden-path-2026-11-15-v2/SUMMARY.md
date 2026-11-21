# MVP-3 synthetic golden path

This pack contains one declared-synthetic natural-person account and one declared-synthetic United States equity. It records the ordered cause chain from application through the daily close. No event was submitted to a venue, depository, bank, or regulator.

Evidence digest: `sha256:65aab9195aeae3729be18bca3a642a5d87a8141538866777922fd02e03e8f350`

Every clean-run invariant in `evidence-pack.json` is true.

## Change from the prior pack

| Figure | Prior pack | This pack | Reason |
| --- | --- | --- | --- |
| Account activation sequence | ACTIVE before execution | ACTIVE after settlement and books posting | The signed first-trade record must cause activation only after the first trade posts to books. |
| Evidence events | 13 | 14 | The activation event is now explicit in the cause chain. |
| Evidence digest | `sha256:194fa15ca909bb890a3cc5b60a183850b0f6a828d271d9b1f0a0ef1f010da78f` | `sha256:65aab9195aeae3729be18bca3a642a5d87a8141538866777922fd02e03e8f350` | The corrected event order changes the replayed digest. |
