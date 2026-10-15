from tms.simulated import SimulatedTms


def _ledger(shipment_id: str) -> list[dict]:
    """Successful simulated writes recorded by earlier processing runs."""
    from processing.models import TmsWrite

    return list(
        TmsWrite.objects.filter(shipment_id=shipment_id, mode="mock", status=TmsWrite.Status.SUCCESS)
        .order_by("id")
        .values("operation", "reference", "request_summary")
    )


def get_tms_client(config):
    """Return the client for the configured TMS_MODE. Only the simulated TMS exists so far."""
    if config.tms_mode == "mock":
        return SimulatedTms(list(config.tms_fixture_dirs), ledger=_ledger)
    raise ValueError(f"TMS_MODE={config.tms_mode} is not available yet. The sandbox client is not built.")
