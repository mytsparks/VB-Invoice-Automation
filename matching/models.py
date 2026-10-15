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
    """Snapshot of a shipment as read from the TMS at match time."""

    shipment_id = models.CharField(max_length=20, unique=True)
    turvo_id = models.CharField(max_length=30, blank=True)
    carrier = models.ForeignKey(Carrier, null=True, blank=True, on_delete=models.SET_NULL)
    carrier_name = models.CharField(max_length=200, blank=True)
    container_number = models.CharField(max_length=30, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    total_cost = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    status = models.CharField(max_length=50, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(auto_now=True)


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
        OVERRIDDEN = "overridden", "Approved despite flags"

    invoice = models.OneToOneField(Invoice, on_delete=models.CASCADE, related_name="match_result")
    shipment = models.ForeignKey(ShipmentRecord, null=True, blank=True, on_delete=models.SET_NULL)
    tolerance_rule = models.ForeignKey(ToleranceRule, null=True, blank=True, on_delete=models.SET_NULL)
    outcome = models.CharField(max_length=20, choices=Outcome.choices, default=Outcome.PENDING)
    order_id = models.BigIntegerField(null=True, blank=True, help_text="Carrier order in the TMS the invoice was compared to.")
    comparison = models.JSONField(default=list, blank=True, help_text="Rows of field, invoice value, TMS value and result.")
    notes = models.JSONField(default=list, blank=True)
    suggestions = models.JSONField(default=list, blank=True, help_text="Shipment IDs offered when no match was found.")
    shipment_confirmed_by_user = models.BooleanField(default=False)
    override_note = models.TextField(blank=True)
    overridden_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def can_process(self) -> bool:
        return self.outcome in (self.Outcome.READY, self.Outcome.OVERRIDDEN) and self.shipment_id is not None


class Flag(models.Model):
    match_result = models.ForeignKey(MatchResult, on_delete=models.CASCADE, related_name="flags")
    flag_type = models.ForeignKey(FlagType, on_delete=models.PROTECT)
    field = models.CharField(max_length=100, blank=True)
    invoice_value = models.CharField(max_length=200, blank=True)
    shipment_value = models.CharField(max_length=200, blank=True)
    rule = models.CharField(max_length=200, blank=True)
    explanation = models.TextField(blank=True)
