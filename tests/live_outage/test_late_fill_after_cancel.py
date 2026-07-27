from btc_scraper.execution.live_outage import CancelReplaceCoordinator
from tests.live_outage.helpers import outage_paths


def test_late_fill_after_cancel_is_accounted_once(tmp_path):
    paths = outage_paths(tmp_path)
    coordinator = CancelReplaceCoordinator(paths["cancel_replace"])

    coordinator.request_cancel_unknown(original_order_id="orig-late", target_quantity=2.0)
    coordinator.record_original_fill(original_order_id="orig-late", quantity=0.4, fill_id="late-fill")
    replay = coordinator.record_original_fill(original_order_id="orig-late", quantity=0.4, fill_id="late-fill")
    coordinator.reconcile_original(original_order_id="orig-late", status="CANCELED")
    replacement = coordinator.create_replacement(original_order_id="orig-late", replacement_order_id="replace-late")

    assert replay["original_filled_quantity"] == 0.4
    assert replacement["replacement_quantity"] == 1.6
