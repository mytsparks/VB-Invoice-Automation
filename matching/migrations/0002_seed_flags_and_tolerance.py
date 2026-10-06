from decimal import Decimal

from django.db import migrations

FLAGS = [
    ("duplicate_invoice", "Duplicate invoice"),
    ("no_matching_shipment", "No matching shipment found"),
    ("low_confidence", "Low extraction confidence"),
    ("amount_over_tolerance", "Amount over tolerance"),
    ("unknown_accessorial", "Unknown or unbilled accessorial"),
    ("currency_mismatch", "Currency mismatch"),
    ("carrier_mismatch", "Carrier mismatch"),
    ("missing_required_field", "Missing required field"),
    ("math_mismatch", "Math does not reconcile"),
    ("possible_fraud", "Possible fraud or tampering"),
]


def seed(apps, schema_editor):
    FlagType = apps.get_model("matching", "FlagType")
    ToleranceRule = apps.get_model("matching", "ToleranceRule")
    for code, name in FLAGS:
        FlagType.objects.get_or_create(code=code, defaults={"name": name})
    ToleranceRule.objects.get_or_create(
        version=1,
        carrier=None,
        defaults={
            "amount_pct": Decimal("1.000"),
            "amount_fixed": Decimal("5.00"),
            "min_confidence": 0.85,
            "notes": "Starting values only. Confirm with the client before relying on them.",
        },
    )


class Migration(migrations.Migration):
    dependencies = [("matching", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
