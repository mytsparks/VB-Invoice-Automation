Project Context

Overview

Vineyard Brokerage is a logistics and customs brokerage company with operations in the US, Canada and India. This project is a Kelley School of Business MSIS capstone that automates the accounts payable invoice intake process for the company. The client sponsor is Garry Dhaliwal.

Problem

Carrier invoices arrive by email as scanned PDFs or images. They have no set format and vary by carrier. Each invoice is currently entered into Turvo TMS by hand, which is slow and error-prone. Turvo's native platform handles execution and document capture well, but it has limited built-in invoice audit automation. Freight audit and pay is typically handled through third-party partners, and Vineyard has no existing OCR tooling.

Scope

In scope
- Document intake from the invoice intake email inbox.
- Extraction of invoice data from scanned PDFs and images.
- Invoice-to-shipment matching logic.
- An audit GUI for the India-based review team.

Out of scope
- Accounts receivable.

The first development iteration is a command line prototype. The audit GUI follows in a later iteration.

Current Process

Invoices are emailed to an intake inbox, and staff key the data into Turvo manually. The India-based review team will be the primary users of the audit GUI.

Team

- Myles Sparks, team lead. Owns timeline, task and deadline tracking. Plans the schedule in a Gantt chart and runs day-to-day work in Kanban.
- Mischa Dzubay, team member.
- Angel Hernandez, team member.
- Garry Dhaliwal, client sponsor.

Timeline and Cadence

The project runs Weeks 3-16, from September to December 2026. Core work is targeted for completion by mid-November, and the engagement wraps by the end of December. The weekly client meeting is on Wednesdays at 4:00 PM, which began September 2.

Access and Resources

The team has direct access to the invoice intake email inbox. Turvo sandbox API credentials were still outstanding at the last update.
