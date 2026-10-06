"""Ground truth labels, kept apart from operational data so evaluation never leaks into the pipeline."""
from django.db import models


class GroundTruthInvoice(models.Model):
    file_name = models.CharField(max_length=255, unique=True)
    shipment_id = models.CharField(max_length=20, blank=True)
    carrier_name = models.CharField(max_length=200, blank=True)
    invoice_number = models.CharField(max_length=100, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)


class GroundTruthLine(models.Model):
    invoice = models.ForeignKey(GroundTruthInvoice, on_delete=models.CASCADE, related_name="lines")
    charge_type = models.CharField(max_length=200, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
