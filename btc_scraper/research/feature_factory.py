"""
btc_scraper/research/feature_factory.py
Phase M3-B: Point-in-Time Technical & Multi-Timeframe Feature Factory.

Guarantees:
1. Strict Point-in-Time (PIT) isolation: no feature at time T uses data after T.
2. Exact numerical parity between vectorized batch processing and step-by-step replay inference.
3. Multi-timeframe closed-candle synchronization: higher timeframe bars are only observed
   once their close_time <= base_bar_close_time.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import numpy as np

from btc_scraper.research.feature_contract import (
    FeatureSetSpec,
    M3_STANDARD_FEATURE_NAMES,
)


class FeatureFactory:
    """
    Computes Point-in-Time technical and MTF features from normalized candle dictionaries.
    Supports both batch execution and sequential replay mode with proven numerical parity.
    """

    def __init__(self, spec: FeatureSetSpec):
        self.spec = spec
        self.params = spec.feature_parameters
        self.rsi_period = int(self.params.get("rsi_period", 14))
        self.macd_fast = int(self.params.get("macd_fast", 12))
        self.macd_slow = int(self.params.get("macd_slow", 26))
        self.macd_signal = int(self.params.get("macd_signal", 9))
        self.atr_period = int(self.params.get("atr_period", 14))
        self.vol_period = int(self.params.get("volatility_period", 20))
        self.volume_period = int(self.params.get("volume_period", 20))

    def compute_batch_features(
        self,
        candles: Sequence[Mapping[str, Any]],
        mtf_candles: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
    ) -> List[Dict[str, float]]:
        """
        Computes features over the entire candle sequence.
        Returns a list of feature dictionaries, one for each candle in `candles`.
        """
        n = len(candles)
        if n == 0:
            return []

        # Extract base series
        closes = np.array([float(c["close"]) for c in candles], dtype=np.float64)
        opens = np.array([float(c["open"]) for c in candles], dtype=np.float64)
        highs = np.array([float(c["high"]) for c in candles], dtype=np.float64)
        lows = np.array([float(c["low"]) for c in candles], dtype=np.float64)
        volumes = np.array([float(c["volume"]) for c in candles], dtype=np.float64)
        close_times = [str(c.get("close_time", "")) for c in candles]

        # 1. Base returns
        ret_1 = np.zeros(n, dtype=np.float64)
        ret_4 = np.zeros(n, dtype=np.float64)
        ret_12 = np.zeros(n, dtype=np.float64)
        ret_48 = np.zeros(n, dtype=np.float64)
        log_ret_1 = np.zeros(n, dtype=np.float64)

        if n > 1:
            ret_1[1:] = (closes[1:] - closes[:-1]) / np.maximum(closes[:-1], 1e-8)
            log_ret_1[1:] = np.log(np.maximum(closes[1:], 1e-8) / np.maximum(closes[:-1], 1e-8))
        if n > 4:
            ret_4[4:] = (closes[4:] - closes[:-4]) / np.maximum(closes[:-4], 1e-8)
        if n > 12:
            ret_12[12:] = (closes[12:] - closes[:-12]) / np.maximum(closes[:-12], 1e-8)
        if n > 48:
            ret_48[48:] = (closes[48:] - closes[:-48]) / np.maximum(closes[:-48], 1e-8)

        # 2. Volatility and ATR
        hl_spread = (highs - lows) / np.maximum(closes, 1e-8)

        tr = np.zeros(n, dtype=np.float64)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )

        atr_14 = np.zeros(n, dtype=np.float64)
        natr_14 = np.zeros(n, dtype=np.float64)
        for i in range(n):
            start_idx = max(0, i - self.atr_period + 1)
            atr_14[i] = np.mean(tr[start_idx : i + 1])
            natr_14[i] = atr_14[i] / max(closes[i], 1e-8)

        volatility_20 = np.zeros(n, dtype=np.float64)
        for i in range(n):
            start_idx = max(0, i - self.vol_period + 1)
            window = ret_1[start_idx : i + 1]
            volatility_20[i] = float(np.std(window)) if len(window) > 1 else 0.0

        # 3. Oscillators: RSI(14)
        rsi_14 = np.full(n, 50.0, dtype=np.float64)
        gains = np.maximum(ret_1, 0.0)
        losses = np.maximum(-ret_1, 0.0)

        for i in range(1, n):
            start_idx = max(1, i - self.rsi_period + 1)
            avg_gain = float(np.mean(gains[start_idx : i + 1]))
            avg_loss = float(np.mean(losses[start_idx : i + 1]))
            if avg_loss < 1e-12:
                rsi_14[i] = 100.0 if avg_gain > 0 else 50.0
            else:
                rs = avg_gain / avg_loss
                rsi_14[i] = 100.0 - (100.0 / (1.0 + rs))

        # 4. MACD(12, 26, 9)
        alpha_fast = 2.0 / (self.macd_fast + 1.0)
        alpha_slow = 2.0 / (self.macd_slow + 1.0)
        alpha_sig = 2.0 / (self.macd_signal + 1.0)

        ema_fast = np.zeros(n, dtype=np.float64)
        ema_slow = np.zeros(n, dtype=np.float64)
        macd_line = np.zeros(n, dtype=np.float64)
        macd_signal = np.zeros(n, dtype=np.float64)
        macd_hist = np.zeros(n, dtype=np.float64)
        macd_hist_norm = np.zeros(n, dtype=np.float64)

        ema_fast[0] = closes[0]
        ema_slow[0] = closes[0]
        macd_line[0] = 0.0
        macd_signal[0] = 0.0

        for i in range(1, n):
            ema_fast[i] = alpha_fast * closes[i] + (1.0 - alpha_fast) * ema_fast[i - 1]
            ema_slow[i] = alpha_slow * closes[i] + (1.0 - alpha_slow) * ema_slow[i - 1]
            macd_line[i] = ema_fast[i] - ema_slow[i]
            macd_signal[i] = alpha_sig * macd_line[i] + (1.0 - alpha_sig) * macd_signal[i - 1]
            macd_hist[i] = macd_line[i] - macd_signal[i]
            macd_hist_norm[i] = macd_hist[i] / max(closes[i], 1e-8)

        # 5. SMA ratios
        sma_dist_20 = np.zeros(n, dtype=np.float64)
        sma_dist_50 = np.zeros(n, dtype=np.float64)
        for i in range(n):
            idx_20 = max(0, i - 19)
            sma_20 = float(np.mean(closes[idx_20 : i + 1]))
            sma_dist_20[i] = (closes[i] / max(sma_20, 1e-8)) - 1.0

            idx_50 = max(0, i - 49)
            sma_50 = float(np.mean(closes[idx_50 : i + 1]))
            sma_dist_50[i] = (closes[i] / max(sma_50, 1e-8)) - 1.0

        # 6. Volume ratios
        vol_ratio_20 = np.ones(n, dtype=np.float64)
        vol_z_20 = np.zeros(n, dtype=np.float64)
        for i in range(n):
            start_idx = max(0, i - self.volume_period + 1)
            vol_window = volumes[start_idx : i + 1]
            v_mean = float(np.mean(vol_window))
            v_std = float(np.std(vol_window))
            vol_ratio_20[i] = volumes[i] / max(v_mean, 1e-8)
            vol_z_20[i] = (volumes[i] - v_mean) / max(v_std, 1e-8)

        # 7. MTF Features (Point-in-Time aligned to base candle close_time)
        mtf_1h_ret = np.zeros(n, dtype=np.float64)
        mtf_1h_trend = np.zeros(n, dtype=np.float64)
        mtf_4h_ret = np.zeros(n, dtype=np.float64)
        mtf_4h_trend = np.zeros(n, dtype=np.float64)

        if mtf_candles:
            if "1h" in mtf_candles:
                c1h = mtf_candles["1h"]
                mtf_1h_ret, mtf_1h_trend = self._compute_htf_alignment(close_times, c1h)
            if "4h" in mtf_candles:
                c4h = mtf_candles["4h"]
                mtf_4h_ret, mtf_4h_trend = self._compute_htf_alignment(close_times, c4h)

        # Assemble row dictionaries
        features: List[Dict[str, float]] = []
        for i in range(n):
            row = {
                "ret_1": float(ret_1[i]),
                "ret_4": float(ret_4[i]),
                "ret_12": float(ret_12[i]),
                "ret_48": float(ret_48[i]),
                "log_ret_1": float(log_ret_1[i]),
                "atr_14": float(atr_14[i]),
                "natr_14": float(natr_14[i]),
                "volatility_20": float(volatility_20[i]),
                "hl_spread": float(hl_spread[i]),
                "rsi_14": float(rsi_14[i]),
                "macd_line": float(macd_line[i]),
                "macd_signal": float(macd_signal[i]),
                "macd_hist": float(macd_hist[i]),
                "macd_hist_norm": float(macd_hist_norm[i]),
                "sma_dist_20": float(sma_dist_20[i]),
                "sma_dist_50": float(sma_dist_50[i]),
                "vol_ratio_20": float(vol_ratio_20[i]),
                "vol_z_20": float(vol_z_20[i]),
                "mtf_1h_ret_1": float(mtf_1h_ret[i]),
                "mtf_1h_trend": float(mtf_1h_trend[i]),
                "mtf_4h_ret_1": float(mtf_4h_ret[i]),
                "mtf_4h_trend": float(mtf_4h_trend[i]),
            }
            features.append(row)

        return features

    def compute_replay_features(
        self,
        candle_history: Sequence[Mapping[str, Any]],
        mtf_history: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
    ) -> Dict[str, float]:
        """
        Computes features for the single latest candle using historical context.
        Must produce identical numerical output to the last element of compute_batch_features.
        """
        if not candle_history:
            return {k: 0.0 for k in M3_STANDARD_FEATURE_NAMES}

        # Vectorized batch over the supplied window ensures 100% mathematical parity
        all_features = self.compute_batch_features(candle_history, mtf_history)
        return all_features[-1]

    def _compute_htf_alignment(
        self,
        base_close_times: Sequence[str],
        htf_candles: Sequence[Mapping[str, Any]],
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Point-in-Time synchronization: for each base candle closing at T, finds
        the latest HTF candle closing at or before T (htf.close_time <= T).
        Computes return and SMA20 trend distance of that closed HTF candle.
        """
        n_base = len(base_close_times)
        rets = np.zeros(n_base, dtype=np.float64)
        trends = np.zeros(n_base, dtype=np.float64)

        if not htf_candles:
            return rets, trends

        htf_closes = np.array([float(c["close"]) for c in htf_candles], dtype=np.float64)
        htf_close_times = [str(c.get("close_time", "")) for c in htf_candles]
        n_htf = len(htf_candles)

        # Precalculate HTF 1-bar returns and SMA20 trends
        htf_ret_1 = np.zeros(n_htf, dtype=np.float64)
        if n_htf > 1:
            htf_ret_1[1:] = (htf_closes[1:] - htf_closes[:-1]) / np.maximum(htf_closes[:-1], 1e-8)

        htf_sma20_dist = np.zeros(n_htf, dtype=np.float64)
        for j in range(n_htf):
            start_j = max(0, j - 19)
            mean_sma = float(np.mean(htf_closes[start_j : j + 1]))
            htf_sma20_dist[j] = (htf_closes[j] / max(mean_sma, 1e-8)) - 1.0

        # Monotonic two-pointer matching (base close times are sorted, htf close times are sorted)
        htf_idx = 0
        for i, t_close in enumerate(base_close_times):
            while htf_idx + 1 < n_htf and htf_close_times[htf_idx + 1] <= t_close:
                htf_idx += 1

            if htf_idx < n_htf and htf_close_times[htf_idx] <= t_close:
                rets[i] = htf_ret_1[htf_idx]
                trends[i] = htf_sma20_dist[htf_idx]

        return rets, trends
