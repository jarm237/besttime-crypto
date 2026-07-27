from btc_scraper.execution.live_outage import ChildOrderStore
from tests.live_outage.helpers import outage_paths


def test_child_order_state_survives_restart(tmp_path):
    paths = outage_paths(tmp_path)
    first = ChildOrderStore(paths["children"])
    first.create_parent(parent_order_id="parent-1", symbol="BTCUSDT", requested_quantity=1.0)
    first.record_child(
        parent_order_id="parent-1",
        child_order_id="child-1",
        child_sequence=1,
        client_order_id="client-child-1",
        exchange_order_id="ex-child-1",
        requested_quantity=0.5,
    )

    restarted = ChildOrderStore(paths["children"])
    snapshot = restarted.snapshot()

    assert snapshot["parents"]["parent-1"]["requested_quantity"] == 1.0
    assert snapshot["children"]["child-1"]["client_order_id"] == "client-child-1"
