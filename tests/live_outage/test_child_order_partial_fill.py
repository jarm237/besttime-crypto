from btc_scraper.execution.live_outage import ChildOrderStore
from tests.live_outage.helpers import outage_paths


def test_child_partial_fill_and_duplicate_callback_are_idempotent(tmp_path):
    paths = outage_paths(tmp_path)
    store = ChildOrderStore(paths["children"])
    store.create_parent(parent_order_id="parent-partial", symbol="BTCUSDT", requested_quantity=1.0)
    store.record_child(
        parent_order_id="parent-partial",
        child_order_id="child-partial",
        child_sequence=1,
        client_order_id="client-child-partial",
        requested_quantity=0.6,
    )

    first = store.record_child_fill(child_order_id="child-partial", quantity=0.25, fill_id="fill-1")
    duplicate = store.record_child_fill(child_order_id="child-partial", quantity=0.25, fill_id="fill-1")

    assert first["status"] == "recorded"
    assert duplicate["status"] == "duplicate_ignored"
    child = store.snapshot()["children"]["child-partial"]
    assert child["filled_quantity"] == 0.25
    assert child["remaining_quantity"] == 0.35
