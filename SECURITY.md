# Security policy

## Reporting a vulnerability

Please report security problems **privately**. Do not open a public issue, pull request or discussion for a suspected vulnerability — a public report discloses the problem before it can be fixed.

To report privately:

1. Go to this repository's **Security** tab on GitHub.
2. Choose **Report a vulnerability**. This opens a private advisory that only you and the maintainer, Bill Ravelo, can see.

Include what you found, how to reproduce it, and what you believe the impact is. You will get an acknowledgement, and the fix and any disclosure will be coordinated with you in that private advisory.

## Scope

Project Atreides is a research governance layer. **It never submits to a settlement rail
and never holds submission credentials.** It prepares ISO 20022 artefacts for an entitled
member to submit under their own credentials; `is_submission` is `Literal[False]` and no
submit path exists anywhere in the framework.

Reports are welcome, and in particular: anything that would let an agent output move a
lifecycle object, anything that would let a gate pass on missing evidence, anything that
would let an emitted message assert a settlement that did not occur, and anything that
would let a halt be bypassed.

## Supported versions

Only the latest commit on `main` is supported.
