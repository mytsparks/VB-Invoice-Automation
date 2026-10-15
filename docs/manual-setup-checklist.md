Manual Setup Checklist

This lists everything the team adds by hand before or during Iteration 1, and where each item goes. Claude Code builds synthetic data for testing, so development can begin before every item arrives.

Credentials

All credentials go in a .env file at the repository root, created by copying .env.example. Each teammate keeps their own .env. Share secrets only through a password manager, never through chat, email or the repository.

- ANTHROPIC_API_KEY is needed now. Create a dedicated key for this project in the Claude Console, set a spend limit on it, and give each teammate their own key so usage can be traced.
- CLAUDE_MODEL has a default and only needs changing if the team wants a different model.
- DJANGO_SECRET_KEY is needed now. Generate a random value locally. It is not shared and not reused anywhere else.
- Turvo sandbox values are needed only when the client provides them. These are TURVO_BASE_URL, TURVO_SANDBOX_HOST, TURVO_API_KEY, TURVO_CLIENT_ID, TURVO_CLIENT_SECRET, TURVO_USERNAME and TURVO_PASSWORD. The exact set depends on how Turvo issues sandbox access, so confirm it against the Turvo API specification and adjust .env.example if needed. Until then leave TMS_MODE set to mock.
- ALLOW_REAL_INVOICES_TO_LLM is the switch that lets real invoices go to the Claude API. The client has approved this, so each teammate sets it to true when they are ready.

Not needed yet are email inbox credentials, SharePoint access, any production Turvo access, and any Azure or other extraction service keys.

Documents and Data

Needed to start
1. Turvo API specification, placed in docs/reference as turvo-openapi.json or turvo-openapi.yaml. This stops Claude Code from guessing endpoints and field names.
2. Prior project documents, placed in docs/reference. The most useful are the technical design, the data dictionary workbook, the backlog and test plan workbook, the development plan, the validation plan deck, the project charter and the PostgreSQL schema script. The schema and data dictionary were written for PostgreSQL and will be adapted to SQLite.
3. Sample invoices, placed in data/inbox. Aim for 20 to 30 files across as many carriers as possible, including poor scans, multi-page files, image files, a few duplicates and two or three non-invoice attachments such as a bill of lading or proof of delivery. Real invoices are approved for use with the Claude API.

Needed for realistic testing
4. Shipment data for the sample invoices, placed in data/fixtures/shipments. Export the matching shipment records from the sandbox or from Turvo as JSON where possible. Include shipment ID, carrier, container number, dates, status, and cost lines with amounts and currency.
5. Ground truth labels, placed in data/ground_truth. One CSV row per labeled invoice with file name, shipment ID, carrier, invoice number, invoice date, currency and total, plus a second CSV for line items. Aim for at least 15 labeled invoices.
6. Carrier reference list, placed in data/reference as carriers.csv, with canonical carrier names and known spellings or aliases.
7. Tolerance notes, placed in docs/reference as tolerance-notes.md, recording what the client agrees to for amount tolerance, confidence thresholds and handling of unlisted charges.
Optional
8. A copy of the easy-pay spreadsheet if the client confirms access, placed in data/reference. It informs the later QuickPay work and is not used in this iteration.
9. Notes from the AP walkthrough or the current SharePoint workflow, placed in docs/reference.

Before Processing Real Invoices

- The repository is private and contains no real invoices or secrets. Run the secret scan before pushing.
- Every teammate has their own API key with a spend limit.
