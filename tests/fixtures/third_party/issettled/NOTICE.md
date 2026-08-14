# Third-party ISO 20022 sample messages

Source: https://github.com/issettled/iso20022-issettled
Licence: Apache License 2.0 (full text in `LICENSE` alongside this file)
Retrieved: 14 August 2026

Unmodified copies of three `pacs.002.001.11` status reports published by
IsSettled. Retained verbatim, including the proprietary envelope and the
XML signature block, because the point of holding them is that they are not
what this framework would have written.

## Why these are here

Every other message fixture in this repository is either a published ISO
schema or a document this framework generated to exercise its own parser.
Both are necessary and neither answers the question that matters: **does the
parser survive a message somebody else actually sent?**

These do not test the ISO standard. They test the gap between the standard
and a real implementation of it - which is the gap `DepositoryProfile`
exists for, and the gap that decides whether an integration takes a week or
a quarter.

## What they immediately exposed

The pacs.002 payload in these files is **not the document root.** It sits
inside a proprietary `urn:issettled` envelope alongside a business
application header and an XML signature, and the `FIToFIPmtStsRpt` element
itself carries the envelope's namespace while its children carry the ISO
one.

The first version of this parser keyed off the root element and its
namespace, and refused all three files. That was over-strict in a way that
would have read as "the venue is non-conformant" when the venue's ISO
payload was in fact well-formed and correctly namespaced. The parser now
locates the payload by its own namespace instead of assuming it is the root.

This is not a hypothetical that was reasoned about. It is a defect these
files found on the day they were added.

## What they are not

IsSettled is one implementation, not a market infrastructure. Nothing here
is evidence about how any depository, central counterparty or payment system
formats its messages, and no venue profile should be populated from them.
