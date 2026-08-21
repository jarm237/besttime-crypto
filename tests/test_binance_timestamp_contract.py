from __future__ import annotations

import asyncio

from btc_scraper.exchanges.binance import _utc_candle_time, fetch_ohlcv, fetch_ohlcv_tf
from btc_scraper.exchanges.binance_ws import _parse_kline_event


class _Response:
    def __init__(self, payload: list[list[object]]) -> None:
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def raise_for_status(self) -> None:
        return None

    async def json(self) -> list[list[object]]:
        return self.payload


class _Session:
    def __init__(self, payload: list[list[object]]) -> None:
        self.payload = payload

    def get(self, *_args, **_kwargs) -> _Response:
        return _Response(self.payload)


def _kline(open_time_ms: int) -> list[object]:
    return [open_time_ms, "1", "2", "0.5", "1.5", "10"]


def test_binance_epoch_milliseconds_serialize_as_aware_utc():
    assert _utc_candle_time(0) == "1970-01-01T00:00:00Z"
    assert _utc_candle_time(1_786_704_300_000) == "2026-08-14T10:45:00Z"


def test_binance_rest_producers_emit_aware_utc():
    payload = [_kline(1_786_704_300_000)]
    session = _Session(payload)

    candles = asyncio.run(fetch_ohlcv("BTC", session=session))
    tf_candles = asyncio.run(fetch_ohlcv_tf("BTC", "15m", 1, session=session))

    assert candles[0]["time_utc"] == "2026-08-14T10:45:00Z"
    assert tf_candles[0]["time_utc"] == "2026-08-14T10:45:00Z"
    assert candles[0]["time"] == tf_candles[0]["time"]


def test_binance_websocket_producer_emits_same_aware_utc_contract():
    parsed = _parse_kline_event(
        {
            "e": "kline",
            "s": "BTCUSDT",
            "k": {
                "t": 1_786_704_300_000,
                "i": "15m",
                "x": True,
                "o": "1",
                "h": "2",
                "l": "0.5",
                "c": "1.5",
                "v": "10",
            },
        }
    )

    assert parsed is not None
    assert parsed["candle"]["time_utc"] == "2026-08-14T10:45:00Z"
