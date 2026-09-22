# Contributing

Thank you for looking. A note on what this repository is, before anything else.

## What this is

Project Atreides is a governance layer for multi-asset settlement. It governs the
decision behind a settlement instruction. **It never submits to a rail and never holds
submission credentials** — it prepares artefacts for an entitled member to submit under
their own.

**It is research.** It is not a product, it is not audited, and nothing in it has been used to move real money. The README carries the same claim label, and it is the honest one.

## Reporting a problem

**Security problems go privately**, through the Security tab — see `SECURITY.md`. Do not open a public issue for a suspected vulnerability.

Everything else: open an issue. The most useful report names what you expected, what happened, and how to reproduce it. A report that says a number is wrong and shows where it came from is worth more than one that says the design is wrong.

## Pull requests

Contributions are welcome, and a few house rules will save you rework. They are not style preferences; each was earned by a defect.

**One work package per commit, with its tests.** A commit that mixes a security change, a lifecycle-semantics change and a presentation change cannot be reviewed or reverted independently.

**Missing evidence returns HOLD or INDETERMINATE — never PASS.** This is the single rule the whole programme rests on. A value that could not be read, a source that failed, a check that did not run: none of them is a pass. If you find code that treats an absence as a success, that is a bug and a welcome report.

**Absence is a value with a reason.** Where a thing is not known, say so and say why. `None`, an empty string and a blank cell are indistinguishable from a value that has not arrived yet, and a reader will pick the cheerful reading.

**State provenance.** A number carries where it came from and when it was seen. A reading with no source is not evidence.

**Write the reasoning down.** A verdict with no reasoning is one nobody can disagree with. Commit messages and comments here explain *why*, at length, on purpose — they are the part that survives.

## Checks

```
uv sync --locked --extra dev
ruff check .
mypy atreides tests
pytest
```

Property tests run under Hypothesis at 200 examples by default; `pytest --hypothesis-profile=deep` runs 2,000 and is the one to run before a release.

Continuous integration runs these on every pull request, whatever branch it targets. Read the **annotations** as well as the pass or fail: a warning sits happily on a green run.

## What is out of scope

Feature requests that would make this move money, submit to a rail, or act without a human. The design refuses those deliberately, and a contribution that adds one will be declined however well it is written.

## Licence

By contributing you agree your contribution is licensed under this repository's licence, in `LICENSE`.
