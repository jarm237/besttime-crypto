from btc_scraper.execution.recovery import PositionProjectionStore
from btc_scraper.execution.reservation_store import ReservationStore
from tests.recovery.helpers import make_coordinator, seed_prediction


def _business_snapshot(paths, prediction_id: str, reservation_id: str):
    coord = make_coordinator(paths)
    reservation = ReservationStore(paths["reservations"]).get_reservation(reservation_id)
    return {
        "predictions": coord.evidence_store.count_rows("predictions"),
        "feature_snapshots": coord.evidence_store.count_rows("feature_snapshots"),
        "final_decisions": coord.evidence_store.count_rows("final_decisions"),
        "outcome_links": coord.evidence_store.count_rows("outcome_links"),
        "decision": coord.evidence_store.get_final_decision_for_prediction(prediction_id),
        "reservation": reservation.to_dict() if reservation else None,
        "ledger": coord.ledger.snapshot(),
        "positions": PositionProjectionStore(paths["positions"]).snapshot(),
        "latest_outcomes": coord.evidence_store.latest_outcomes(),
    }


def test_recovery_pipeline_is_idempotent_across_three_restarts(recovery_paths):
    seed = make_coordinator(recovery_paths)
    prediction = seed_prediction(seed.evidence_store, "pred-multi-restart")
    fill = {
        "exchange_trade_id": "trade-multi-restart",
        "client_order_id": "client-multi-restart",
        "exchange_order_id": "ex-multi-restart",
        "qty": 0.4,
        "price": 100.0,
        "fee": 0.04,
    }
    outcome = {
        "outcome_id": "out-multi-restart",
        "prediction_id": prediction["prediction_id"],
        "position_id": "pos-multi-restart",
        "outcome_revision": 1,
        "net_pnl_pct": 2.0,
    }

    reservation_id = None
    snapshots = []
    for _ in range(3):
        coord = make_coordinator(recovery_paths)
        decision_result = coord.recover_final_decision(
            prediction["prediction_id"],
            lambda pred: {"decision_id": "ed-multi-restart", "signal_id": pred["signal_id"], "status": "eligible"},
        )
        decision = coord.evidence_store.get_final_decision_for_prediction(prediction["prediction_id"])
        reservation_result = coord.recover_reservation_for_decision(
            {**decision, "idempotency_key": "idem-multi-restart", "reservation_id": "res-multi-restart"},
            symbol="BTCUSDT",
            side="BUY",
            notional_usdt=100.0,
        )
        reservation_id = reservation_result.record_id
        coord.reconcile_ambiguous_submit(
            reservation_id=reservation_id,
            client_order_id="client-multi-restart",
            exchange_lookup=lambda _: [{"client_order_id": "client-multi-restart", "exchange_order_id": "ex-multi-restart"}],
        )
        coord.replay_fill(fill)
        coord.apply_fill_to_position(
            projection_store=PositionProjectionStore(recovery_paths["positions"]),
            position_id="pos-multi-restart",
            order={"prediction_id": prediction["prediction_id"], "client_order_id": "client-multi-restart"},
            fill=fill,
        )
        coord.recover_outcome(outcome)
        assert decision_result.status in {"recovered", "already_recovered"}
        snapshots.append(_business_snapshot(recovery_paths, prediction["prediction_id"], reservation_id))

    assert snapshots[1] == snapshots[0]
    assert snapshots[2] == snapshots[0]
