"""Customer protection challenger engines (ORDER SC-2).

EXPERIMENTAL under the charter section 18.6 claim labels. Nothing in this
package is production evidence, and nothing in it claims regulatory compliance.

A deterministic recomputation of selected, caller-classified net-capital and
customer and PAB (proprietary accounts of broker-dealers) reserve components,
early-warning trigger indicators, and a partial possession-or-control location
and conservation check. It is a challenger: it reads balances and
classifications from a system of record and reports what it computes and where
that differs. It does not establish that the upstream classifications are
correct. It is not the book of record, it files or sends no regulatory notice,
and a FINOP (Financial and Operations Principal) signs whatever is filed.

Rule text is data. Every regulatory figure is read from a pinned copy of the
electronic Code of Federal Regulations (eCFR) text through
:mod:`atreides.customer_protection.rules`, with its citation, retrieval DTG
(date-time group) and content hash. A figure that is not loaded yields
INDETERMINATE, never a default. Missing input balances yield HOLD, never PASS.
A PASS means only that no issue was found within the supplied inputs and the
rules this experimental package models, not that a broker-dealer complies.

Every output is ADVISORY_ONLY. The advisory a computation produces enforces
nothing: no shared attestation contract carries it and no Aureon consumer reads
it, so no gate holds on it. Each computation is recorded in the DSOR (Decision
System of Record) with its inputs, rule versions and result, and replays byte
for byte.

No module in this package imports aureon, L.C. (Legiones Cannenses) or any other
Atreides package, and none reaches the network.
``tools/fetch_customer_protection_rules.py`` is the only code that fetches rule text.
"""
