SYNTHETIC SIMULATION: invariants held on generated data; this is not evidence of production correctness

# SIM-1 run summary

- Seed: `20261024`
- Pack: `stress-2023-03` version `1`
- Manifest: `sha256:db4ba240f71156f3fd98be0956e2cc77be74c4901253a33695f94b4a90a8fb32`
- Classes: `A, B, SYNTHETIC`
- Closes: `31`
- Window: `2023-02-09` through `2023-03-24` (`explicit dated-pack window`)
- Final SOFR: `4.80` percent
- Final financing need: `$97725.95`
- Final financing charge: `$13.03`
- Source commit: `21348fea502dcc8a87e33e70365203c6404efe0d`
- Provenance: locally generated from the locked Mac pack; this folder contains run outputs only, not the pack or its data.

## Reserve protection

- Customer deposit policy: `NOT_DECLARED_IN_PACK`: the pack declares no deposit policy, so no deposit is posted and every positive requirement holds as a shortfall
- Customer reserve: `0` PASS, `31` HOLD (`24` no declared deposit, `0` simulated short or late deposit, `7` missing inputs or other engine reasons)
- PAB deposit policy: `NOT_DECLARED_IN_PACK`: the pack declares no deposit policy, so no deposit is posted and every positive requirement holds as a shortfall
- PAB reserve: `10` PASS, `21` HOLD (`6` no declared deposit, `0` simulated short or late deposit, `15` missing inputs or other engine reasons)

## New York Fed notices

- The SOFR is subject to the Terms of Use posted at newyorkfed.org. The New York Fed is not responsible for publication of the SOFR by Bill Ravelo, CFMA research, does not sanction or endorse any particular republication, and has no liability for your use. Distributed content remains subject to the same permissions, conditions, and restrictions.
- The BGCR is subject to the Terms of Use posted at newyorkfed.org. The New York Fed is not responsible for publication of the BGCR by Bill Ravelo, CFMA research, does not sanction or endorse any particular republication, and has no liability for your use. Distributed content remains subject to the same permissions, conditions, and restrictions.
- The TGCR is subject to the Terms of Use posted at newyorkfed.org. The New York Fed is not responsible for publication of the TGCR by Bill Ravelo, CFMA research, does not sanction or endorse any particular republication, and has no liability for your use. Distributed content remains subject to the same permissions, conditions, and restrictions.
- The EFFR is subject to the Terms of Use posted at newyorkfed.org. The New York Fed is not responsible for publication of the EFFR by Bill Ravelo, CFMA research, does not sanction or endorse any particular republication, and has no liability for your use. Distributed content remains subject to the same permissions, conditions, and restrictions.
- The OBFR is subject to the Terms of Use posted at newyorkfed.org. The New York Fed is not responsible for publication of the OBFR by Bill Ravelo, CFMA research, does not sanction or endorse any particular republication, and has no liability for your use. Distributed content remains subject to the same permissions, conditions, and restrictions.

## Not tested

- second venue
- best execution
- options
- repo
- clearing fund waterfall

- Artifact freshness: `STALE`; source commit `21348fea502dcc8a87e33e70365203c6404efe0d` is behind current main `2610f46696ed26ad24b43c1b350eeef232a4423c`.
