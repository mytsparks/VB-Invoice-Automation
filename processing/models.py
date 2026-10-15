from django.db import models

from extraction.models import Invoice
from intake.models import ProcessingRun


class TmsWrite(models.Model):
    """Every write attempt to a TMS, successful or not. Secrets and file contents are never stored."""

    class Operation(models.TextChoices):
        ATTACH_DOCUMENT = "attach_document", "Attach invoice document"
        RECORD_INVOICE = "record_invoice", "Record carrier invoice"

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="tms_writes")
    processing_run = models.ForeignKey(ProcessingRun, null=True, blank=True, on_delete=models.SET_NULL)
    operation = models.CharField(max_length=30, choices=Operation.choices)
    idempotency_key = models.CharField(max_length=100)
    mode = models.CharField(max_length=20, help_text="mock for the simulated TMS, sandbox for Turvo.")
    shipment_id = models.CharField(max_length=20)
    status = models.CharField(max_length=10, choices=Status.choices)
    http_status = models.IntegerField(null=True, blank=True)
    reference = models.CharField(max_length=100, blank=True, help_text="Document or invoice ID returned by the TMS.")
    request_summary = models.JSONField(default=dict, blank=True)
    response = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    readback_ok = models.BooleanField(null=True, blank=True, help_text="Whether a read after the write showed the change.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["idempotency_key", "mode"],
                condition=models.Q(status="success"),
                name="one_successful_write_per_key",
            )
        ]
