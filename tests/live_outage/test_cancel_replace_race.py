import pytest

from btc_scraper.execution.live_outage import CancelReplaceAmbiguityError, CancelReplaceCoordinator
from tests.live_outage.helpers import outage_paths


def test_cancel_replace_waits_for_original_reconcile_and_subtracts_fill(tmp_path):
    paths = outage_paths(tmp_path)
    coordinator = CancelReplaceCoordinator(paths["cancel_replace"])

    coordinator.request_cancel_unknown(original_order_id="orig-1", target_quantity=1.0)
    with pytest.raises(CancelReplaceAmbiguityError):
        coordinator.create_replacement(original_order_id="orig-1", replacement_order_id="replace-too-early")

    coordinator.record_original_fill(original_order_id="orig-1", quantity=0.35, fill_id="fill-late-1")
    coordinator.reconcile_original(original_order_id="orig-1", status="CANCELED")
    replacement = coordinator.create_replacement(original_order_id="orig-1", replacement_order_id="replace-1")

    assert replacement["replacement_quantity"] == 0.65
    assert replacement["replacement_quantity"] + replacement["original_filled_quantity"] <= replacement["target_quantity"]
