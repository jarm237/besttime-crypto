from tests.recovery.helpers import make_coordinator


def test_partial_fill_replay_counts_fill_once_after_restart(recovery_paths):
    fill = {
        "exchange_trade_id": "trade-partial-1",
        "client_order_id": "client-partial-1",
        "exchange_order_id": "ex-partial-1",
        "qty": 0.25,
        "price": 100.0,
        "fee": 0.01,
    }

    first = make_coordinator(recovery_paths)
    first.ledger.record_order({"client_order_id": "client-partial-1", "exchange_order_id": "ex-partial-1"})
    assert first.replay_fill(fill).status == "linked"

    restarted = make_coordinator(recovery_paths)
    replay = restarted.replay_fill(fill)

    snapshot = restarted.ledger.snapshot()
    assert replay.record_id == "exchange_trade_id:trade-partial-1"
    assert snapshot["fill_count"] == 1
    assert snapshot["pending_fill_count"] == 0
    order = next(iter(snapshot["orders"].values()))
    assert order["fill_keys"] == ["exchange_trade_id:trade-partial-1"]
