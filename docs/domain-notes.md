Domain Notes

Turvo TMS

Turvo is Vineyard's transportation management system and the system of record for shipments. It handles execution and document capture well. It does not provide much built-in invoice audit automation, so audit and matching is handled outside it. Sandbox API credentials have not been received yet, so the exact API surface, authentication and available shipment fields are unconfirmed.

Shipment Identifiers

Shipment IDs follow the format 31xxx-xxxxx, for example 31234-56789, and are typically printed on carrier invoices. A reasonable starting pattern is a regular expression for 31 followed by three digits, a hyphen and five digits. Confirm against real samples, since OCR errors in scanned documents can alter characters, and some invoices may omit the ID or print it in a different place.

The container number lives on the shipment record in Turvo and does not appear on the invoice. It can be used to verify or disambiguate a match after a shipment is found, but it cannot be used as a key read from the invoice.

Carrier Invoices

- They arrive as scanned PDFs or images attached to emails.
- There is no standard layout, and formats differ by carrier.
- Scan quality will vary, so extraction needs a confidence measure and a human review path.
- One email may contain several attachments or several invoices, and some attachments may not be invoices at all.

Fields Likely Needed From Each Invoice

These are working assumptions to confirm with the client and with real samples.

- Shipment ID
- Carrier name
- Invoice number and invoice date
- Total amount and currency
- Line items and charge types
- Any additional reference numbers printed on the invoice

Matching Considerations

- The shipment ID is the primary match key. An exact match on a valid ID, plus an amount and carrier sanity check against the shipment record, is the high-confidence case.
- When the ID is missing or unreadable, fall back to other references and carrier, date and amount signals, and send the result to human review.
- Duplicate invoices for the same shipment should be detected and flagged.
- Because operations span the US, Canada and India, currency and date formats may vary.
- The audit GUI exists so that a person confirms anything that is not a clean match.
