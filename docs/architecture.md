Architecture

This describes the structure for Iteration 1, a command line prototype on Python, Django and SQLite. The team can change it as decisions are made. The data dictionary and technical design in docs/reference take precedence on details when they are present.

Pipeline

1. Intake registers files from the local inbox folder, records a content hash and skips exact duplicates.
2. Extraction sends each document to the Claude API with a versioned prompt and a typed output schema, and stores raw output and normalized values separately.
3. Matching finds the shipment using the printed shipment ID and loads the shipment record through the TMS client.
4. Validation applies versioned tolerance rules, raises the ten flags and sets an outcome of ready or needs review.
5. Reporting writes the daily processing summary and a review list as CSV files.

6. Processing sends invoices marked ready to the configured TMS, which is the simulated TMS by default and the Turvo sandbox when access exists. It attaches the invoice document, posts the cost line and records every write.

The audit GUI, reviewer decisions and any write to a production TMS come in later iterations.

Django Layout

One Django project with a few small apps. Management commands are the command line interface.

- intake covers file registration and document records.
- extraction covers the extraction adapter, the Claude implementation, the prompt library loader and result storage.
- matching covers shipment resolution, tolerance rules, flags and outcomes.
- reporting covers the evaluation, daily summary and review list commands.
- tms is a plain Python package with the client interface, the simulated implementation and the guarded sandbox implementation, both of which can read and write.
- config holds the settings module, secret handling and guardrail checks.

Prompts live in a versioned prompts folder at the repository root.

Data Model Outline

- Document for the stored file, content hash, source and status.
- ExtractionRun for the model, prompt version, raw output, token usage and estimated cost.
- Invoice and InvoiceLine for normalized extracted values and confidence.
- ShipmentRecord for shipment data loaded from the TMS client.
- MatchResult and Flag for the decision, the rule that fired and the compared values.
- Carrier and CarrierAlias for canonical names and known spellings.
- ToleranceRule for versioned rules with per-carrier overrides.
- ProcessingRun for each batch, which feeds the daily summary.
- GroundTruthLabel tables kept separate from operational data.

Design Notes

- Every pipeline stage records a status so it can be rerun safely.
- Extraction results are cached by content hash, prompt version and model.
- The TMS client is an interface, so the simulated and sandbox implementations are interchangeable.
- Every TMS write is recorded with an idempotency key, so a rerun never writes the same thing twice.
- Secrets and client data follow the guardrails in PLAN.md.
