Status and Open Items

Status as of September 30, 2026

- No application code has been written yet.
- Stack is decided as Python, Django (ORM and management commands now, GUI later) and SQLite.
- Extraction will use the Claude API, as decided in the team's earlier slide deck.
- Iteration 1 is command line only, and the audit GUI is deferred to the next iteration.
- Turvo write-back, QuickPay logic, and email and SharePoint intake are deferred. Iteration 1 reads invoices from a local folder.
- The team has direct access to the invoice intake email inbox and can download sample attachments by hand.
- Turvo sandbox API credentials are treated as outstanding until the team confirms receipt.

Blockers

- Turvo sandbox API credentials and the Turvo API specification in docs/reference. Until they arrive, build against the mock TMS.
- Written client approval to send real invoices to the Claude API. Until then, use synthetic samples only.

Open Decisions

- Whether the audit GUI is a standalone Django application or something embedded in or linked from Turvo.
- Whether and when Turvo write-back enters scope.
- Carriers and weekly invoice volume the prototype should handle, and how many samples the client can provide.
- Tolerance values and confidence thresholds the client is comfortable with.
- How the India-based review team works today, including hours, volume and approval rules.
- Hosting approach for later iterations, which was raised for discussion with the client.

Next Steps

Follow PLAN.md from Phase 1. The team adds documents, data and credentials as listed in docs/manual-setup-checklist.md.
