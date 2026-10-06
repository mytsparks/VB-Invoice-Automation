Data Folder

Everything in this folder is ignored by git except this file and data/synthetic. Never commit real invoices or client data.

data/inbox holds invoice files to process.
data/ground_truth holds labeled values for evaluation.
data/fixtures/shipments holds shipment records used by the mock TMS.
data/reference holds carrier lists and other client reference files.
data/synthetic holds fake invoices and fixtures that are safe to commit and use in tests.
The SQLite database is stored here by default.
