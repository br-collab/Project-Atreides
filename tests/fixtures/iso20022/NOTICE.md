# ISO 20022 message schemas — provenance and an unresolved question

## What these files are

`pacs.008.001.14.xsd`, `pacs.009.001.13.xsd`, `pacs.002.001.16.xsd` and
`head.001.001.04.xsd` are ISO 20022 message definition schemas published by the
ISO 20022 Registration Authority.

They are held here **so that messages this framework emits are validated against
the real schema rather than against a paraphrase of it**. That is the whole
reason: a test that checks emitted XML against a hand-written approximation
proves that the approximation and the code agree, which is not the claim anybody
wants.

They are unmodified. No ISO 20022 schema is redistributed as part of any
artefact this repository publishes — they are test fixtures, used at test time,
and nothing in `atreides/` reads them.

## The redistribution terms could not be verified

**This is the honest state, and it is recorded rather than resolved.**

Research Charter § 18.6 and the joint upgrade map § 10.4 require the
redistribution terms of any third-party material to be verified before
publication is relied on. On 21 September 2026 that verification was attempted
and **did not succeed**:

- `https://www.iso20022.org/terms-conditions` returned **HTTP 403** to an
  automated request.
- `https://www.iso20022.org/iso-20022-message-definitions` returned **HTTP 403**
  likewise.
- A public search returned no definitive statement of the redistribution terms
  for catalogue message schemas. The one licence statement found concerned a
  three-month trial licence for a revision under review, which is a different
  thing and does not govern these files.

So this notice does **not** claim that redistribution is permitted, and it does
not claim it is forbidden. It records that the question is open.

`DATA-PROVENANCE.md` describes these schemas as *"published by the Registration
Authority for implementation use"*. That is accurate about why they exist and is
**not** a redistribution grant, and it should not be read as one.

## What has not been done, deliberately

**Nothing has been removed.** The tasking order that raised this
(`W3-agent-activation-AMD2.md` § 3) is explicit: if the terms forbid
redistribution, report it, and do not remove anything without Bill. The terms
were not established either way, so removing files would act on a conclusion
nobody reached.

## What would settle it

A reading of the ISO 20022 Registration Authority's terms of use by someone who
can retrieve them — the site refuses automated requests, so a browser or an
approach to the Registration Authority is needed. Two answers are useful:

1. whether the schemas may be redistributed at all, and
2. whether holding them as test fixtures in a public repository counts as
   redistribution, which is the specific question here.

Until then this file is the record that the question was asked, and by whom, and
what the answer was not.

## The other fixtures in this tree are settled

`tests/fixtures/third_party/issettled/` is different and is not in question:
three `pacs.002` status reports from `github.com/issettled/iso20022-issettled`,
retrieved 14 August 2026, under the **Apache License 2.0**, with the full licence
text and `NOTICE.md` alongside them. Apache 2.0 permits redistribution, so those
travel lawfully under this repository's own grant. See `DATA-PROVENANCE.md`.
