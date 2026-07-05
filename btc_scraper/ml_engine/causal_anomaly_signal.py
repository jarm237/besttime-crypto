"""
CausalAnomalySignalGenerator - Tạo tín hiệu CAUSAL ANOMALY từ quan hệ coin causal.

Logic cốt lõi:
  - Dùng CoinCausalGraph để biết coin nào là leader, coin nào là follower
  - Dự báo expected_return(follower) = weighted_sum(leader_returns tại lag)
  - deviation = actual_return(follower) - expected_return
  - causal_anomaly_score = rolling z-score của deviation
  - CAUSAL ANOMALY khi |z| > threshold (mặc định 2.0)

Tín hiệu:
  z > +2.0 → Follower STRONGER than leader predicts → Bullish Divergence
  z < -2.0 → Follower WEAKER  than leader predicts → Bearish Divergence

Features Output (per coin, per timestamp):
  - causal_anomaly_score      : z-score (float)
  - causal_expected_return    : kỳ vọng return từ leaders
  - causal_deviation          : actual - expected
  - causal_lead_lag_signal    : "BUY" | "SELL" | "NEUTRAL"
  - causal_breakout_flag      : 1 nếu |z| >= strong_threshold, else 0
  - causal_num_leaders        : số lượng leaders tác động
  - causal_leader_names       : tên các leaders (comma-separated)
  - causal_divergence_type    : "BULLISH" | "BEARISH" | "NONE"

Usage:
    from btc_scraper.ml_engine.coin_causal_finder import CoinCausalRelationFinder
    from btc_scraper.ml_engine.causal_anomaly_signal import CausalAnomalySignalGenerator

    # Bước 1: Tìm graph
    finder = CoinCausalRelationFinder()
    data = finder.generate_demo_data()
    graph = finder.run(data)

    # Bước 2: Tạo tín hiệu
    gen = CausalAnomalySignalGenerator()
    signals_df = gen.generate(data, graph, target_coin="ETH")
    print(signals_df[["causal_anomaly_score", "causal_lead_lag_signal"]].tail(10))
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from btc_scraper.ml_engine.coin_causal_finder import (
    CoinCausalGraph,
    CoinCausalRelationFinder,
    CoinPair,
)

logger = logging.getLogger(__name__)


# ─── Config ───────────────────────────────────────────────────────────────────

@dataclass
class CausalAnomalyConfig:
    """Cấu hình cho CausalAnomalySignalGenerator."""

    # Z-score threshold để phát hiện anomaly thông thường
    anomaly_z_threshold: float = 2.0

    # Z-score threshold để phát hiện anomaly mạnh (strong signal)
    strong_z_threshold: float = 3.0

    # Rolling window để tính rolling z-score (số candles)
    rolling_window: int = 48

    # Số candles tối thiểu trước khi tính z-score (warmup)
    min_warmup_periods: int = 24

    # Minimum confidence của pair để tính expected return
    min_pair_confidence: float = 0.50

    # Có lấy weighted average (theo confidence) hay simple average
    use_weighted_leaders: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Result Structures ────────────────────────────────────────────────────────

@dataclass
class AnomalyPoint:
    """Kết quả anomaly tại một điểm thời gian cho một coin."""
    timestamp: int            # index position
    coin: str
    actual_return: float
    expected_return: float
    deviation: float
    anomaly_score: float      # z-score
    signal: str               # "BUY" | "SELL" | "NEUTRAL"
    breakout_flag: int        # 1 nếu strong anomaly
    divergence_type: str      # "BULLISH" | "BEARISH" | "NONE"
    num_leaders: int
    leader_names: str


@dataclass
class CausalAnomalyReport:
    """Báo cáo tổng thể cho một coin."""
    coin: str
    n_anomalies: int
    n_bullish: int
    n_bearish: int
    n_strong: int
    avg_anomaly_score: float
    max_anomaly_score: float
    anomaly_rate: float       # % candles có anomaly
    points: List[AnomalyPoint] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "coin": self.coin,
            "n_anomalies": self.n_anomalies,
            "n_bullish": self.n_bullish,
            "n_bearish": self.n_bearish,
            "n_strong": self.n_strong,
            "avg_anomaly_score": round(self.avg_anomaly_score, 4),
            "max_anomaly_score": round(self.max_anomaly_score, 4),
            "anomaly_rate": round(self.anomaly_rate, 4),
        }


# ─── Main Generator ───────────────────────────────────────────────────────────

class CausalAnomalySignalGenerator:
    """
    Tạo tín hiệu CAUSAL ANOMALY từ CoinCausalGraph và dữ liệu giá.

    Phát hiện khi một follower coin lệch khỏi kỳ vọng từ leader coin.
    """

    def __init__(self, config: Optional[CausalAnomalyConfig] = None) -> None:
        self.config = config or CausalAnomalyConfig()

    # ── Public API ──────────────────────────────────────────────────────────

    def generate(
        self,
        price_data: pd.DataFrame,
        graph: CoinCausalGraph,
        target_coin: Optional[str] = None,
        price_col_suffix: str = "",
    ) -> pd.DataFrame:
        """
        Tạo causal anomaly features cho tất cả (hoặc một) coin.

        Args:
            price_data: DataFrame với columns = tên coin (giá close).
            graph: CoinCausalGraph từ CoinCausalRelationFinder.
            target_coin: Nếu chỉ muốn tính cho một coin. None = tất cả.
            price_col_suffix: Suffix của column name.

        Returns:
            DataFrame với causal anomaly features được thêm vào.
        """
        # Tính returns
        returns = self._compute_returns(price_data, graph.coins, price_col_suffix)
        out = returns.copy()

        coins_to_process = [target_coin] if target_coin else graph.coins

        for coin in coins_to_process:
            if coin not in returns.columns:
                continue

            leaders = graph.get_leaders_of(coin)
            leaders = [
                p for p in leaders
                if p.confidence >= self.config.min_pair_confidence
            ]

            if not leaders:
                # Không có leader → điền default values
                out = self._fill_no_leaders(out, coin)
                continue

            out = self._compute_anomaly_features(out, coin, leaders, returns)

        return out

    def generate_report(
        self,
        price_data: pd.DataFrame,
        graph: CoinCausalGraph,
    ) -> Dict[str, CausalAnomalyReport]:
        """
        Tạo báo cáo CAUSAL ANOMALY cho tất cả follower coins trong graph.

        Returns:
            Dict: coin → CausalAnomalyReport
        """
        signals_df = self.generate(price_data, graph)
        reports: Dict[str, CausalAnomalyReport] = {}

        follower_coins = list(set(p.follower for p in graph.pairs))
        for coin in follower_coins:
            score_col = f"causal_anomaly_score_{coin}"
            flag_col = f"causal_breakout_flag_{coin}"
            div_col = f"causal_divergence_type_{coin}"

            if score_col not in signals_df.columns:
                continue

            scores = signals_df[score_col].dropna()
            if len(scores) == 0:
                continue

            n_anom = int((scores.abs() >= self.config.anomaly_z_threshold).sum())
            n_bull = int(
                (signals_df.get(div_col, pd.Series()) == "BULLISH").sum()
            )
            n_bear = int(
                (signals_df.get(div_col, pd.Series()) == "BEARISH").sum()
            )
            n_strong = int(
                (signals_df.get(flag_col, pd.Series()) == 1).sum()
            )

            reports[coin] = CausalAnomalyReport(
                coin=coin,
                n_anomalies=n_anom,
                n_bullish=n_bull,
                n_bearish=n_bear,
                n_strong=n_strong,
                avg_anomaly_score=float(scores.abs().mean()),
                max_anomaly_score=float(scores.abs().max()),
                anomaly_rate=n_anom / len(scores) if len(scores) > 0 else 0.0,
            )

        return reports

    # ── Core Computation ────────────────────────────────────────────────────

    def _compute_anomaly_features(
        self,
        out: pd.DataFrame,
        coin: str,
        leaders: List[CoinPair],
        returns: pd.DataFrame,
    ) -> pd.DataFrame:
        """Tính causal anomaly features cho một follower coin."""
        actual_ret = returns[coin] if coin in returns.columns else pd.Series(
            0.0, index=returns.index
        )

        # Tính expected return = weighted sum của leader returns tại lag
        expected_ret = self._compute_expected_return(leaders, returns)

        # Deviation = actual - expected
        deviation = actual_ret - expected_ret

        # Rolling z-score của deviation
        z_score = self._rolling_zscore(deviation)

        # Signals
        signal = z_score.map(self._zscore_to_signal)
        breakout = (z_score.abs() >= self.config.strong_z_threshold).astype(int)
        divergence = z_score.map(self._zscore_to_divergence_type)

        # Leader metadata
        num_leaders = len(leaders)
        leader_names = ",".join(p.leader for p in leaders)

        # Assign columns — dùng coin suffix để multi-coin coexist
        suffix = f"_{coin}"
        out[f"causal_anomaly_score{suffix}"] = z_score
        out[f"causal_expected_return{suffix}"] = expected_ret
        out[f"causal_deviation{suffix}"] = deviation
        out[f"causal_lead_lag_signal{suffix}"] = signal
        out[f"causal_breakout_flag{suffix}"] = breakout
        out[f"causal_divergence_type{suffix}"] = divergence
        out[f"causal_num_leaders{suffix}"] = num_leaders
        out[f"causal_leader_names{suffix}"] = leader_names

        logger.debug(
            f"[CausalAnomalySignal] {coin}: {num_leaders} leaders, "
            f"anomaly_rate={float((z_score.abs() >= self.config.anomaly_z_threshold).mean()):.2%}"
        )
        return out

    def _compute_expected_return(
        self,
        leaders: List[CoinPair],
        returns: pd.DataFrame,
    ) -> pd.Series:
        """
        Tính expected return của follower từ các leaders.

        expected = Σ (weight_i * leader_return_i_lagged)
        """
        total_weight = sum(p.confidence for p in leaders) if self.config.use_weighted_leaders else len(leaders)
        if total_weight == 0:
            return pd.Series(0.0, index=returns.index)

        expected = pd.Series(0.0, index=returns.index)

        for pair in leaders:
            if pair.leader not in returns.columns:
                continue

            leader_ret = returns[pair.leader]
            # Shift theo lag: leader_return tại t-lag ảnh hưởng follower tại t
            lag = max(pair.lag, 1)
            lagged_ret = leader_ret.shift(lag)

            # Effect direction: negative → đảo chiều
            direction = -1.0 if pair.effect == "negative" else 1.0

            w = pair.confidence if self.config.use_weighted_leaders else 1.0
            expected += direction * w * lagged_ret * pair.weight

        # Normalize by total weight
        expected /= total_weight
        return expected.fillna(0.0)

    def _rolling_zscore(self, series: pd.Series) -> pd.Series:
        """Tính rolling z-score với warmup protection."""
        window = self.config.rolling_window
        min_periods = self.config.min_warmup_periods

        rolling_mean = series.rolling(window=window, min_periods=min_periods).mean()
        rolling_std = series.rolling(window=window, min_periods=min_periods).std()

        # Tránh division by zero
        rolling_std = rolling_std.replace(0.0, np.nan)

        z = (series - rolling_mean) / rolling_std
        z = z.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        return z

    # ── Signal Mapping ──────────────────────────────────────────────────────

    def _zscore_to_signal(self, z: float) -> str:
        """Chuyển z-score thành trading signal."""
        if np.isnan(z):
            return "NEUTRAL"
        if z >= self.config.anomaly_z_threshold:
            return "BUY"
        if z <= -self.config.anomaly_z_threshold:
            return "SELL"
        return "NEUTRAL"

    def _zscore_to_divergence_type(self, z: float) -> str:
        """Phân loại divergence từ z-score."""
        if np.isnan(z):
            return "NONE"
        if z >= self.config.anomaly_z_threshold:
            return "BULLISH"
        if z <= -self.config.anomaly_z_threshold:
            return "BEARISH"
        return "NONE"

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _compute_returns(
        self,
        data: pd.DataFrame,
        coins: List[str],
        suffix: str,
    ) -> pd.DataFrame:
        """Tính stationary returns."""
        ret_dict = {}
        for coin in coins:
            col = f"{coin}{suffix}" if suffix else coin
            if col not in data.columns:
                col = next(
                    (c for c in data.columns if c.upper() == coin.upper()), None
                )
            if col is None or col not in data.columns:
                continue

            series = pd.to_numeric(data[col], errors="coerce")
            if series.std(skipna=True) > 0.5:
                ret = series.pct_change().replace([np.inf, -np.inf], np.nan)
            else:
                ret = series
            ret_dict[coin] = ret

        returns = pd.DataFrame(ret_dict)
        return returns

    def _fill_no_leaders(self, out: pd.DataFrame, coin: str) -> pd.DataFrame:
        """Điền giá trị mặc định khi coin không có leader nào."""
        suffix = f"_{coin}"
        out[f"causal_anomaly_score{suffix}"] = 0.0
        out[f"causal_expected_return{suffix}"] = 0.0
        out[f"causal_deviation{suffix}"] = 0.0
        out[f"causal_lead_lag_signal{suffix}"] = "NEUTRAL"
        out[f"causal_breakout_flag{suffix}"] = 0
        out[f"causal_divergence_type{suffix}"] = "NONE"
        out[f"causal_num_leaders{suffix}"] = 0
        out[f"causal_leader_names{suffix}"] = ""
        return out


# ─── Convenience function ─────────────────────────────────────────────────────

def build_causal_anomaly_features(
    price_data: pd.DataFrame,
    coins: Optional[List[str]] = None,
    config: Optional[CausalAnomalyConfig] = None,
    finder_kwargs: Optional[dict] = None,
) -> Tuple[pd.DataFrame, CoinCausalGraph]:
    """
    All-in-one function: tìm causal relations + tạo anomaly features.

    Args:
        price_data: DataFrame giá coin (columns = coin names).
        coins: Danh sách coins muốn phân tích.
        config: CausalAnomalyConfig (optional).
        finder_kwargs: Tham số cho CoinCausalRelationFinder (optional).

    Returns:
        (features_df, coin_graph)
    """
    from btc_scraper.ml_engine.coin_causal_finder import CoinCausalRelationFinder

    kwargs = finder_kwargs or {}
    if coins:
        kwargs["coins"] = coins

    finder = CoinCausalRelationFinder(**kwargs)
    graph = finder.run(price_data)

    gen = CausalAnomalySignalGenerator(config=config)
    features_df = gen.generate(price_data, graph)

    return features_df, graph


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    coins = ["BTC", "ETH", "SOL", "BNB", "LINK", "DOGE", "MATIC", "XRP"]

    print("=" * 70)
    print("CausalAnomalySignalGenerator — Demo Run")
    print("=" * 70)

    # Step 1: Tạo data và chạy finder
    print("\n[1] Generating demo price data...")
    data = CoinCausalRelationFinder.generate_demo_data(coins=coins, n=600)
    print(f"    Shape: {data.shape}")

    print("\n[2] Running CoinCausalRelationFinder...")
    finder = CoinCausalRelationFinder(coins=coins, max_lag=8)
    graph = finder.run(data)
    print(f"    {graph.summary()}")

    # Step 2: Tạo anomaly signals
    print("\n[3] Generating CAUSAL ANOMALY signals...")
    config = CausalAnomalyConfig(
        anomaly_z_threshold=2.0,
        strong_z_threshold=3.0,
        rolling_window=48,
    )
    gen = CausalAnomalySignalGenerator(config=config)
    signals_df = gen.generate(data, graph)

    # Step 3: Report
    print("\n[4] Anomaly Report per coin:")
    reports = gen.generate_report(data, graph)
    if not reports:
        print("    (Không có follower coins nào được phân tích)")
    else:
        for coin, rpt in sorted(reports.items()):
            print(
                f"    {coin:6s}: anomalies={rpt.n_anomalies:3d} "
                f"(bull={rpt.n_bullish}, bear={rpt.n_bearish}, strong={rpt.n_strong}) | "
                f"rate={rpt.anomaly_rate:.1%} | "
                f"max_z={rpt.max_anomaly_score:.2f}"
            )

    # Step 4: Show recent signals for ETH
    print("\n[5] Recent signals for ETH (last 10 rows):")
    eth_cols = [c for c in signals_df.columns if c.endswith("_ETH")]
    if eth_cols:
        print(signals_df[eth_cols].tail(10).to_string())
    else:
        print("    ETH không phải follower trong graph này")

    print(f"\n[6] Total features generated: {len(signals_df.columns)}")
    causal_cols = [c for c in signals_df.columns if c.startswith("causal_")]
    print(f"    Causal features: {len(causal_cols)}")
    print(f"    Feature names: {causal_cols[:8]}{'...' if len(causal_cols) > 8 else ''}")
