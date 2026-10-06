from django.db import models

from intake.models import Document, ProcessingRun


class ExtractionRun(models.Model):
    """One extraction attempt for a document. Raw model output is kept exactly as returned."""

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        INVALID = "invalid", "Output failed schema validation"
        REFUSED = "refused", "Model declined"
        ERROR = "error", "API error"

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="extraction_runs")
    processing_run = models.ForeignKey(ProcessingRun, null=True, blank=True, on_delete=models.SET_NULL)
    model = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices)
    attempts = models.IntegerField(default=1)
    raw_output = models.TextField(blank=True)
    error = models.TextField(blank=True, help_text="Error text only. Never document content.")
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    cache_read_tokens = models.IntegerField(default=0)
    cache_write_tokens = models.IntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    request_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.document} / {self.prompt_version} / {self.status}"


class Invoice(models.Model):
    """Normalized values for one invoice found in a document. Raw output lives on ExtractionRun."""

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="invoices")
    extraction_run = models.ForeignKey(ExtractionRun, on_delete=models.CASCADE, related_name="invoices")
    position = models.IntegerField(default=1, help_text="Order within the document.")

    shipment_id = models.CharField(max_length=20, blank=True, help_text="Only set when it matches 31xxx-xxxxx.")
    shipment_id_raw = models.CharField(max_length=100, blank=True)
    carrier_name = models.CharField(max_length=200, blank=True)
    invoice_number = models.CharField(max_length=100, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    other_references = models.JSONField(default=list, blank=True)
    overall_confidence = models.FloatField(default=0)
    field_details = models.JSONField(
        default=dict,
        blank=True,
        help_text="Per field printed text, confidence, rationale and source page.",
    )
    notes = models.TextField(blank=True)
    review_reasons = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["document_id", "position"]

    @property
    def needs_review(self) -> bool:
        return bool(self.review_reasons)

    def __str__(self):
        return f"{self.carrier_name} {self.invoice_number}".strip() or f"Invoice {self.pk}"


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    position = models.IntegerField()
    charge_type = models.CharField(max_length=200, blank=True)
    description = models.CharField(max_length=500, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    confidence = models.FloatField(default=0)
    page = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["invoice_id", "position"]
