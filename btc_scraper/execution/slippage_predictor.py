"""
btc_scraper/execution/slippage_predictor.py
Phase 10 – Sprint 10.3: Slippage Predictor

v1: rule-based formula (plan § 8.1)
v2: LightGBM ML model (loaded if slippage_model_v2.joblib exists)

The predictor is used BEFORE an order is submitted to decide
whether the trade is worth placing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class SlippagePredictorV1:
    """
    Rule-based slippage predictor.

    expected_slippage_bps = (
        base_slippage_bps
        + 0.3 * spread_bps
        + 0.2 * atr_pct_as_bps        # atr_pct * 10000 → bps equivalent
        + 0.4 * order_size_pct_depth   # (order_notional / depth_5bps) * 100
        + 0.2 * volatility_score       # normalised
        - 0.2 * liquidity_score        # [0,1] – higher liq → less slippage
    )
    """

    def __init__(self, config: Dict[str, Any] = None):
        cfg = config or {}
        self.base_slippage_bps: float = cfg.get("base_slippage_bps", 1.0)

    def predict(
        self,
        spread_bps: float = 0.0,
        atr_pct: float = 0.0,
        order_notional_usdt: float = 0.0,
        depth_5bps_usdt: float = 1.0,
        liquidity_score: float = 0.5,
        volatility_score: float = 0.5,
    ) -> float:
        """Returns expected slippage in bps."""
        order_size_pct_depth = (
            (order_notional_usdt / depth_5bps_usdt * 100.0)
            if depth_5bps_usdt > 0 else 100.0
        )
        atr_bps = atr_pct * 10_000.0

        slippage = (
            self.base_slippage_bps
            + 0.3 * spread_bps
            + 0.2 * atr_bps
            + 0.4 * order_size_pct_depth
            + 0.2 * (volatility_score * 100.0)
            - 0.2 * (liquidity_score * 100.0)
        )
        return max(0.0, round(slippage, 4))


class SlippagePredictorV2:
    """
    ML slippage predictor backed by LightGBM.
    Falls back to v1 if model file is missing.
    """

    FEATURE_COLS = [
        "spread_bps", "atr_pct", "volume_1m_usdt", "volume_5m_usdt",
        "orderbook_imbalance", "depth_5bps_usdt", "depth_10bps_usdt",
        "latency_ms", "liquidity_score", "order_notional_usdt",
        "order_size_pct_depth", "volatility_score",
    ]

    def __init__(self, model_path: str = "slippage_model_v2.joblib",
                 config: Dict[str, Any] = None):
        self._v1 = SlippagePredictorV1(config)
        self._model = None
        self._model_path = Path(model_path)
        self._load_model()

    def _load_model(self) -> None:
        try:
            from btc_scraper.ml_engine.governed_artifact_loader import get_governed_artifact_loader
            loaded = get_governed_artifact_loader().load_production("slippage_model_v2", "slippage-v2-12f")
            self._model = loaded.model
            logger.info("Loaded governed slippage model %s", loaded.artifact_id)
        except Exception as e:
            logger.info("Governed slippage model unavailable: %s — using rule-based v1", e)

    def predict(
        self,
        spread_bps: float = 0.0,
        atr_pct: float = 0.0,
        order_notional_usdt: float = 0.0,
        depth_5bps_usdt: float = 1.0,
        depth_10bps_usdt: float = 2.0,
        liquidity_score: float = 0.5,
        volatility_score: float = 0.5,
        volume_1m_usdt: float = 0.0,
        volume_5m_usdt: float = 0.0,
        orderbook_imbalance: float = 0.0,
        latency_ms: int = 0,
    ) -> float:
        """Returns expected slippage in bps (ML or rule-based fallback)."""
        if self._model is not None:
            try:
                import numpy as np
                order_size_pct_depth = (
                    order_notional_usdt / depth_5bps_usdt * 100.0
                    if depth_5bps_usdt > 0 else 100.0
                )
                features = np.array([[
                    spread_bps, atr_pct, volume_1m_usdt, volume_5m_usdt,
                    orderbook_imbalance, depth_5bps_usdt, depth_10bps_usdt,
                    latency_ms, liquidity_score, order_notional_usdt,
                    order_size_pct_depth, volatility_score,
                ]])
                pred = float(self._model.predict(features)[0])
                return max(0.0, round(pred, 4))
            except Exception as e:
                logger.warning(f"ML predict failed: {e} — using v1 fallback")

        # Rule-based fallback
        return self._v1.predict(
            spread_bps=spread_bps,
            atr_pct=atr_pct,
            order_notional_usdt=order_notional_usdt,
            depth_5bps_usdt=depth_5bps_usdt,
            liquidity_score=liquidity_score,
            volatility_score=volatility_score,
        )

    @property
    def is_ml_active(self) -> bool:
        return self._model is not None


class SlippagePredictor:
    """
    Unified predictor entrypoint — auto-selects v2 (ML) when available.
    """
    def __init__(self, config: Dict[str, Any] = None, model_path: str = "slippage_model_v2.joblib"):
        self._v2 = SlippagePredictorV2(model_path=model_path, config=config)

    def predict(self, **kwargs) -> float:
        return self._v2.predict(**kwargs)

    def predict_from_snapshot(self, snap, order_notional_usdt: float, latency_ms: int = 0) -> float:
        """Convenience wrapper that accepts a LiquiditySnapshot object."""
        depth_5bps = (snap.bid_depth_5bps + snap.ask_depth_5bps) / 2.0 or 1.0
        depth_10bps = (snap.bid_depth_10bps + snap.ask_depth_10bps) / 2.0 or 2.0
        return self.predict(
            spread_bps=snap.spread_bps,
            atr_pct=snap.atr_pct,
            order_notional_usdt=order_notional_usdt,
            depth_5bps_usdt=depth_5bps,
            depth_10bps_usdt=depth_10bps,
            liquidity_score=snap.liquidity_score,
            volatility_score=snap.atr_pct * 20.0,   # rough volatility score
            volume_1m_usdt=snap.volume_1m_usdt,
            volume_5m_usdt=snap.volume_5m_usdt,
            orderbook_imbalance=snap.orderbook_imbalance,
            latency_ms=latency_ms,
        )

    @property
    def is_ml_active(self) -> bool:
        return self._v2.is_ml_active
