# CLAUDE.md — Project Atreides

Project Atreides is the post-trade settlement, finality, and reconciliation repository.

- **Boundary:** Atreides never gains submission capability or submission credentials.
- **Kernel pin:** `cannae-kernel` v2.0.0.
- **Workspace rules:** `../CLAUDE.md` in the Project Cannae Legion workspace.
- **Reports:** write order reports to the workspace `_reports/` directory.
## Merge authority

Builders open pull requests and may enable auto-merge. A pull request merges only when every
required status check passes on an up-to-date branch. Builders never bypass required checks,
use an admin override, or force-push to main. Only Bill creates tags and releases.
