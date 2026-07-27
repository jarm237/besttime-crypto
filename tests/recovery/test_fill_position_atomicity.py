from btc_scraper.execution.recovery import PositionProjectionStore
from tests.recovery.helpers import make_coordinator


def test_fill_applies_to_position_projection_once_across_restart(recovery_paths):
    order = {
        "prediction_id": "pred-fill-position",
        "client_order_id": "client-fill-position",
        "exchange_order_id": "ex-fill-position",
    }
    fill = {
        "exchange_trade_id": "trade-fill-position",
        "client_order_id": "client-fill-position",
        "qty": 0.5,
        "price": 100.0,
        "fee": 0.05,
    }

    first_projection = PositionProjectionStore(recovery_paths["positions"])
    first = make_coordinator(recovery_paths)
    applied = first.apply_fill_to_position(
        projection_store=first_projection,
        position_id="pos-fill-position",
        order=order,
        fill=fill,
    )
    assert applied.status == "applied"

    restarted_projection = PositionProjectionStore(recovery_paths["positions"])
    replay = make_coordinator(recovery_paths).apply_fill_to_position(
        projection_store=restarted_projection,
        position_id="pos-fill-position",
        order=order,
        fill=fill,
    )

    assert replay.status == "already_applied"
    position = restarted_projection.snapshot()["positions"]["pos-fill-position"]
    assert position["qty"] == 0.5
    assert position["fee"] == 0.05
    assert position["avg_price"] == 100.0
    assert position["fill_keys"] == ["exchange_trade_id:trade-fill-position"]
