# Superseded synthetic golden-path packs

The packs below were built before the MVP-5B cash-account posting correction. They remain
unchanged as historical publications. `mvp5c-closure-2026-11-18` superseded the first five packs;
`ps1b-closure-2026-11-18` now supersedes every pack in this table.

| Pack | Customer cash | Customer credits | Reserve requirement | Reason |
| --- | ---: | ---: | ---: | --- |
| `mvp3-golden-path-2026-11-15` | Not published; underlying run retained 10,000.00 | 10,000.00 | 10,000.00 | The purchase was offset by a customer cash credit |
| `mvp3-golden-path-2026-11-15-v2` | Not published; underlying run retained 10,000.00 | 10,000.00 | 10,000.00 | The purchase was offset by a customer cash credit |
| `mvp3b-golden-path-2026-11-15` | Not published; underlying run retained 10,000.00 | 10,000.00 | 10,000.00 | The purchase was offset by a customer cash credit |
| `mvp4-client-reporting-2026-11-15` | 10,000.00 | 10,000.00 | 10,000.00 | The statement and reserve projection included the offsetting credit |
| `mvp4-client-reporting-2026-11-15-v2` | 10,000.00 | 10,000.00 | 10,000.00 | The statement and reserve projection included the offsetting credit |
| `mvp5b-closure-2026-11-17` | 9,000.00 | 9,000.00 | 9,000.00 | It did not split trade-date ownership from settlement-date street movements or publish cost basis |
| `mvp5c-closure-2026-11-18` | 9,000.00 | 9,000.00 | 9,000.00 | It did not split trade-date ownership from settlement-date street movements or publish cost basis |
| `ps1-books-on-right-date-2026-11-18` | 9,000.00 | 9,000.00 | 9,000.00 | reconciliation rows were constants |
| `ps1b-true-reconciliations-2026-11-18` | 9,000.00 | 9,000.00 | 9,000.00 | It did not yet include the stored KYC chain, tax pins, account-treatment table, or furnished-confirmation customer oracle |

The superseding pack reports customer cash 9,000.00, customer credits 9,000.00 and a reserve
requirement of 9,000.00 because the 1,000.00 purchase reduces free cash without an offsetting
customer credit. Every figure is declared synthetic.

The PS-1B pack retains the PS-1 customer figures and replaces its constant reconciliation rows
with rows projected from the six control completion records.

## SIM-1 runner packs

The three dated runner packs below were rerun from their locked local inputs at
`ead38fe^` (`22cf88d13c073e15cf20bee289ced798e1888257`) and at current main. The
old run passed the drawn customer-credit balance straight into the reserve
engine. Current main seeds the books and drives the estate from those book
entries, so trade activity changes free credits and the reserve requirement.

| Pack | Old reserve-requirement range | New reserve-requirement range | Reason |
| --- | ---: | ---: | --- |
| `spike-2019` | 50,000,000.00 to 900,000,000.00 | 49,995,645.58 to 899,997,311.70 | The runner now derives free credits from seeded books after trade activity |
| `stress-2020-03` | 50,000,000.00 to 900,000,000.00 | 49,995,494.37 to 899,997,723.00 | The runner now derives free credits from seeded books after trade activity |
| `stress-2023-03` | 50,000,000.00 to 900,000,000.00 | 49,995,632.71 to 899,997,723.00 | The runner now derives free credits from seeded books after trade activity |
