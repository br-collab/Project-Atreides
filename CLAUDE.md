# CLAUDE.md — Project Atreides

Project Atreides is the post-trade settlement, finality, and reconciliation repository.

- **Boundary:** Atreides never gains submission capability or submission credentials.
- **Kernel pin:** `cannae-kernel` v2.0.0.
- **Workspace rules:** `../CLAUDE.md` in the Project Cannae Legion workspace.
- **Reports:** write order reports to the workspace `_reports/` directory.
## Merge authority

Builders open pull requests. Only Bill merges pull requests or creates tags. Builders must not enable auto-merge.
