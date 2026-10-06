"""Schema for matching and validation. Nothing writes to these tables yet.

The tables exist now so the extraction data model does not change when the
matching phase is built. Reviewer decisions and QuickPay data are deliberately
left out for later.
"""
from django.db import models

from extraction.models import Invoice


class Carrier(models.Model):
    name = models.CharField(max_length=200, unique=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class CarrierAlias(models.Model):
    carrier = models.ForeignKey(Carrier, on_delete=models.CASCADE, related_name="aliases")
    alias = models.CharField(max_length=200, unique=True, help_text="Stored lower case.")


class FlagType(models.Model):
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class ToleranceRule(models.Model):
    """Versioned so a change never rewrites how an old invoice was judged."""

    version = models.IntegerField()
    carrier = models.ForeignKey(Carrier, null=True, blank=True, on_delete=models.CASCADE)
    amount_pct = models.DecimalField(max_digits=6, decimal_places=3)
    amount_fixed = models.DecimalField(max_digits=10, decimal_places=2)
    min_confidence = models.FloatField(default=0.85)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)


class ShipmentRecord(models.Model):
    shipment_id = models.CharField(max_length=20, unique=True)
    carrier = models.ForeignKey(Carrier, null=True, blank=True, on_delete=models.SET_NULL)
    container_number = models.CharField(max_length=30, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    status = models.CharField(max_length=50, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)


class ShipmentCostLine(models.Model):
    shipment = models.ForeignKey(ShipmentRecord, on_delete=models.CASCADE, related_name="cost_lines")
    charge_type = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=14, decimal_places=4)
    currency = models.CharField(max_length=3, blank=True)


class MatchResult(models.Model):
    class Outcome(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        NEEDS_REVIEW = "needs_review", "Needs review"

    invoice = models.OneToOneField(Invoice, on_delete=models.CASCADE, related_name="match_result")
    shipment = models.ForeignKey(ShipmentRecord, null=True, blank=True, on_delete=models.SET_NULL)
    tolerance_rule = models.ForeignKey(ToleranceRule, null=True, blank=True, on_delete=models.SET_NULL)
    outcome = models.CharField(max_length=20, choices=Outcome.choices, default=Outcome.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)


class Flag(models.Model):
    match_result = models.ForeignKey(MatchResult, on_delete=models.CASCADE, related_name="flags")
    flag_type = models.ForeignKey(FlagType, on_delete=models.PROTECT)
    field = models.CharField(max_length=100, blank=True)
    invoice_value = models.CharField(max_length=200, blank=True)
    shipment_value = models.CharField(max_length=200, blank=True)
    rule = models.CharField(max_length=200, blank=True)
    explanation = models.TextField(blank=True)
