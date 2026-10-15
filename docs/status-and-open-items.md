Status and Open Items

Status as of September 30, 2026

- No application code has been written yet.
- Stack is decided as Python, Django (ORM and management commands now, GUI later) and SQLite.
- Extraction will use the Claude API, as decided in the team's earlier slide deck.
- Iteration 1 is command line only, and the audit GUI is deferred to the next iteration.
- QuickPay logic, and email and SharePoint intake are deferred. Iteration 1 reads invoices from a local folder.
- Iteration 1 reads from and writes to the Turvo sandbox, and never to production. Errors and discrepancies in the sandbox are expected.
- Until Turvo public API access is arranged, shipment extract, compare and process run against a simulated TMS built from fixture files.
- The client has approved sending invoices to the Claude API, because the API does not train on customer data.
- The user makes all git commits and pushes.
- The team has direct access to the invoice intake email inbox and can download sample attachments by hand.
- Turvo sandbox API credentials are treated as outstanding until the team confirms receipt.

Blockers

- Turvo public API access and sandbox credentials. Until they arrive, build against the simulated TMS.

Open Decisions

- Whether the audit GUI is a standalone Django application or something embedded in or linked from Turvo.
- Which write operations processing should use in Turvo, such as attaching the document and posting the cost line, to be confirmed from the API specification.
- Carriers and weekly invoice volume the prototype should handle, and how many samples the client can provide.
- Tolerance values and confidence thresholds the client is comfortable with.
- How the India-based review team works today, including hours, volume and approval rules.
- Hosting approach for later iterations, which was raised for discussion with the client.

Next Steps

Follow PLAN.md from Phase 1. The team adds documents, data and credentials as listed in docs/manual-setup-checklist.md.
