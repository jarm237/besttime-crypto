import pytest

from btc_scraper.execution.live_outage import ChildOrderStore, ParentCompletedError, QuantityInvariantError
from tests.live_outage.helpers import outage_paths


def test_parent_unique_child_fills_never_exceed_requested_quantity(tmp_path):
    paths = outage_paths(tmp_path)
    store = ChildOrderStore(paths["children"])
    store.create_parent(parent_order_id="parent-cap", symbol="BTCUSDT", requested_quantity=1.0)
    store.record_child(
        parent_order_id="parent-cap",
        child_order_id="child-cap-1",
        child_sequence=1,
        client_order_id="client-cap-1",
        requested_quantity=0.6,
    )
    store.record_child(
        parent_order_id="parent-cap",
        child_order_id="child-cap-2",
        child_sequence=2,
        client_order_id="client-cap-2",
        requested_quantity=0.4,
    )
    store.record_child_fill(child_order_id="child-cap-1", quantity=0.6, fill_id="fill-cap-1")
    store.record_child_fill(child_order_id="child-cap-2", quantity=0.4, fill_id="fill-cap-2")

    with pytest.raises(ParentCompletedError):
        store.record_child(
            parent_order_id="parent-cap",
            child_order_id="child-cap-3",
            child_sequence=3,
            client_order_id="client-cap-3",
            requested_quantity=0.1,
        )
    with pytest.raises(QuantityInvariantError):
        store.record_child_fill(child_order_id="child-cap-2", quantity=0.01, fill_id="fill-over")

    assert store.snapshot()["parents"]["parent-cap"]["filled_quantity"] == 1.0
