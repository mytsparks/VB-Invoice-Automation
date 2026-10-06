from django.db import models


class ProcessingRun(models.Model):
    """One execution of a pipeline command. Feeds the daily summary later."""

    command = models.CharField(max_length=50)
    dry_run = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    documents_seen = models.IntegerField(default=0)
    documents_sent = models.IntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.command} #{self.pk}"


class Document(models.Model):
    """A file registered from the inbox. The original file is never modified or moved."""

    class Source(models.TextChoices):
        SYNTHETIC = "synthetic", "Synthetic"
        REAL = "real", "Real client file"

    class Status(models.TextChoices):
        INGESTED = "ingested", "Ingested"
        EXTRACTED = "extracted", "Extracted"
        NON_INVOICE = "non_invoice", "Not an invoice"
        NEEDS_REVIEW = "needs_review", "Extraction failed, needs review"
        UNSUPPORTED = "unsupported", "Unsupported file type"

    path = models.CharField(max_length=500, help_text="Relative to the repository root when possible.")
    file_name = models.CharField(max_length=255)
    content_hash = models.CharField(max_length=64, unique=True)
    size_bytes = models.BigIntegerField()
    media_type = models.CharField(max_length=50, blank=True)
    page_count = models.IntegerField(default=1, help_text="Rough count used for cost estimates.")
    source = models.CharField(max_length=20, choices=Source.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INGESTED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.file_name
