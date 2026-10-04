"""Customer protection challenger engines (ORDER SC-2).

EXPERIMENTAL under the charter section 18.6 claim labels. Nothing in this
package is production evidence, and nothing in it claims regulatory compliance.

An independent, deterministic recomputation of a broker-dealer's net capital
(17 CFR 240.15c3-1), customer and PAB (proprietary accounts of broker-dealers)
reserve formula (17 CFR 240.15c3-3 and its Exhibit A, 240.15c3-3a), early
warning thresholds (17 CFR 240.17a-11), and possession or control of customer
securities (17 CFR 240.15c3-3(b) to (d)). It is a challenger: it reads balances
from a system of record and reports what it computes and where that differs. It
is not the book of record, it files nothing, and a FINOP (Financial and
Operations Principal) signs whatever is filed.

Rule text is data. Every regulatory figure is read from a pinned copy of the
electronic Code of Federal Regulations (eCFR) text through
:mod:`atreides.customer_protection.rules`, with its citation, retrieval DTG
(date-time group) and content hash. A figure that is not loaded yields
INDETERMINATE, never a default. Missing input balances yield HOLD, never PASS.

Every output is ADVISORY_ONLY. The advisory a computation produces enforces
nothing: no shared attestation contract carries it and no Aureon consumer reads
it, so no gate holds on it. Each computation is recorded in the DSOR (Decision
System of Record) with its inputs, rule versions and result, and replays byte
for byte.

No module in this package imports aureon, L.C. (Legiones Cannenses) or any other
Atreides package, and none reaches the network.
``tools/fetch_customer_protection_rules.py`` is the only code that fetches rule text.
"""
