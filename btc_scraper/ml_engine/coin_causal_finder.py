"""
CoinCausalRelationFinder - Tìm quan hệ nhân quả giữa các crypto coins.

Sử dụng Granger Causality + Lagged Correlation để xác định:
  - Coin nào dẫn đầu (leader)
  - Coin nào bị dẫn dắt (follower)
  - Độ trễ (lag) tối ưu giữa các cặp

Kết quả được lưu vào causal_coin_graph.json và dùng bởi
CausalAnomalySignalGenerator để tạo tín hiệu CAUSAL ANOMALY.

Design Principles:
  - Không cần causallearn/tigramite — chỉ dùng numpy/pandas
  - Stationary series (pct_change) để tránh spurious correlation
  - Conservative: cần pass cả correlation VÀ Granger test
  - Cluster-aware: group coins theo Layer1, DeFi, Meme, Exchange

Usage:
    finder = CoinCausalRelationFinder()
    data = finder.load_demo_data()
    graph = finder.run(data)
    finder.save(graph, "data/causal_coin_graph.json")
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─── Coin Universe & Cluster Definitions ──────────────────────────────────────

COIN_CLUSTERS: Dict[str, List[str]] = {
    "Layer1": ["BTC", "ETH", "SOL", "AVAX", "BNB", "TRX", "TON"],
    "DeFi":   ["LINK", "UNI", "AAVE", "COMP", "CRV", "MKR", "SNX"],
    "Meme":   ["DOGE", "SHIB", "PEPE", "FLOKI", "BONK"],
    "Exchange": ["BNB", "OKB", "CRO", "GT"],
    "Layer2": ["MATIC", "OP", "ARB", "IMX", "METIS"],
    "AI":     ["FET", "AGIX", "OCEAN", "RNDR", "WLD"],
    "Other":  ["XRP", "ADA", "DOT", "ATOM", "LTC", "BCH", "ETC"],
}

# Reverse mapping: coin → cluster
COIN_TO_CLUSTER: Dict[str, str] = {}
for _cluster, _coins in COIN_CLUSTERS.items():
    for _coin in _coins:
        if _coin not in COIN_TO_CLUSTER:
            COIN_TO_CLUSTER[_coin] = _cluster

# Default coin universe for analysis
DEFAULT_COINS = [
    "BTC", "ETH", "SOL", "BNB", "XRP",
    "AVAX", "DOGE", "LINK", "MATIC", "OP",
    "ARB", "PEPE", "TON", "ADA", "DOT",
]


# ─── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class CoinPair:
    """Quan hệ nhân quả giữa một cặp coin."""
    leader: str          # coin dẫn đầu (cause)
    follower: str        # coin bị dẫn dắt (effect)
    lag: int             # độ trễ tối ưu (số candles)
    correlation: float   # lagged correlation coefficient
    granger_pvalue: float  # Granger causality p-value
    weight: float        # normalized effect strength [0, 1]
    confidence: float    # tổng hợp từ corr + Granger [0, 1]
    effect: str          # "positive" hoặc "negative"
    leader_cluster: str  # cluster của leader
    follower_cluster: str  # cluster của follower
    is_intra_cluster: bool  # cùng cluster không

    def to_graph_edge(self, edge_id: str) -> Dict:
        """Chuyển sang format causal_coin_graph.json edge."""
        return {
            "id": edge_id,
            "from": self.leader,
            "to": self.follower,
            "effect": self.effect,
            "weight": round(self.weight, 3),
            "lag": f"{self.lag}c",           # c = candles
            "confidence": round(self.confidence, 3),
            "condition": "always",
            "is_active": True,
            "source": "learned",
            "propagate_confidence": True,
            "description": (
                f"Coin causal: {self.leader}→{self.follower} "
                f"(corr={self.correlation:+.3f}, lag={self.lag}, "
                f"p={self.granger_pvalue:.3f})"
            ),
            "leader_cluster": self.leader_cluster,
            "follower_cluster": self.follower_cluster,
            "is_intra_cluster": self.is_intra_cluster,
            "learned_at": datetime.now(timezone.utc).isoformat(),
        }


@dataclass
class CoinCausalGraph:
    """Đồ thị nhân quả cấp coin."""
    pairs: List[CoinPair] = field(default_factory=list)
    coins: List[str] = field(default_factory=list)
    n_samples: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def get_leaders_of(self, follower: str) -> List[CoinPair]:
        """Trả về các coin có thể dẫn dắt follower."""
        return [p for p in self.pairs if p.follower == follower]

    def get_followers_of(self, leader: str) -> List[CoinPair]:
        """Trả về các coin bị dẫn dắt bởi leader."""
        return [p for p in self.pairs if p.leader == leader]

    def get_adjacency(self) -> Dict[str, List[str]]:
        """Dict leader → [followers]."""
        adj: Dict[str, List[str]] = {}
        for p in self.pairs:
            adj.setdefault(p.leader, []).append(p.follower)
        return adj

    def to_json_dict(self) -> Dict:
        """Serialize sang JSON-compatible dict."""
        nodes = [
            {
                "id": coin,
                "cluster": COIN_TO_CLUSTER.get(coin, "Other"),
                "type": "crypto",
            }
            for coin in self.coins
        ]
        edges = [
            pair.to_graph_edge(f"coin_edge_{i+1}")
            for i, pair in enumerate(self.pairs)
        ]
        return {
            "version": "1.0.0",
            "type": "coin_causal_graph",
            "created_at": self.timestamp,
            "n_samples": self.n_samples,
            "coins": self.coins,
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "source": "CoinCausalRelationFinder",
                "num_pairs_found": len(self.pairs),
                "clusters_represented": list(
                    set(COIN_TO_CLUSTER.get(c, "Other") for c in self.coins)
                ),
            },
        }

    def summary(self) -> str:
        intra = sum(1 for p in self.pairs if p.is_intra_cluster)
        inter = len(self.pairs) - intra
        return (
            f"CoinCausalGraph | {len(self.coins)} coins | "
            f"{len(self.pairs)} causal pairs "
            f"({intra} intra-cluster, {inter} inter-cluster) | "
            f"n_samples={self.n_samples}"
        )


# ─── Statistical Tests ────────────────────────────────────────────────────────

def _lagged_correlation(
    x: pd.Series,
    y: pd.Series,
    max_lag: int = 12,
) -> Tuple[int, float]:
    """
    Tìm lag tại đó x tương quan mạnh nhất với y (x là cause, y là effect).

    Returns: (best_lag, best_correlation)
    """
    best_lag = 0
    best_corr = 0.0

    for lag in range(0, max_lag + 1):
        if lag == 0:
            xa, ya = x.align(y, join="inner")
        else:
            xa = x.shift(lag)
            xa, ya = xa.align(y, join="inner")
            xa = xa.dropna()
            ya = ya.loc[xa.index]

        if len(xa) < 30:
            continue

        try:
            corr = float(xa.corr(ya))
            if np.isnan(corr):
                continue
            if abs(corr) > abs(best_corr):
                best_corr = corr
                best_lag = lag
        except Exception:
            continue

    return best_lag, best_corr


def _granger_test(
    cause: pd.Series,
    effect: pd.Series,
    lag: int,
    significance: float = 0.05,
) -> Tuple[bool, float]:
    """
    Simplified Granger causality (F-test, OLS).

    Restricted:   effect_t = a0 + Σ a_i * effect_{t-i}
    Unrestricted: thêm Σ b_i * cause_{t-lag-i}

    Returns: (is_significant, pseudo_pvalue)
    """
    try:
        df = pd.DataFrame({"cause": cause, "effect": effect}).dropna()
        effective_lag = max(lag, 1)

        if len(df) < effective_lag + 30:
            return False, 1.0

        for i in range(1, effective_lag + 1):
            df[f"eff_lag_{i}"] = df["effect"].shift(i)
            df[f"cau_lag_{i}"] = df["cause"].shift(i)
        df = df.dropna()

        if len(df) < 20:
            return False, 1.0

        y = df["effect"].values
        eff_cols = [f"eff_lag_{i}" for i in range(1, effective_lag + 1)]
        cau_cols = [f"cau_lag_{i}" for i in range(1, effective_lag + 1)]

        X_r = np.column_stack([np.ones(len(y)), df[eff_cols].values])
        X_u = np.column_stack([X_r, df[cau_cols].values])

        def _rss(X: np.ndarray, y_arr: np.ndarray) -> float:
            try:
                beta, _, _, _ = np.linalg.lstsq(X, y_arr, rcond=None)
                residuals = y_arr - X @ beta
                return float(np.sum(residuals ** 2))
            except Exception:
                return float("inf")

        rss_r = _rss(X_r, y)
        rss_u = _rss(X_u, y)

        if rss_u <= 0 or rss_r <= 0 or rss_u >= rss_r:
            return False, 1.0

        n = len(y)
        q = effective_lag
        k = X_u.shape[1]
        if n <= k:
            return False, 1.0

        f_stat = ((rss_r - rss_u) / q) / (rss_u / (n - k))
        if f_stat < 0:
            return False, 1.0

        # Conservative p-value approximation
        pseudo_pvalue = float(np.exp(-min(f_stat / 2.0, 20.0)))
        return pseudo_pvalue < significance, pseudo_pvalue

    except Exception as exc:
        logger.debug(f"[CoinCausalFinder] Granger error: {exc}")
        return False, 1.0


# ─── Main Engine ──────────────────────────────────────────────────────────────

class CoinCausalRelationFinder:
    """
    Tìm các cặp coin có quan hệ nhân quả từ dữ liệu time-series.

    Quy trình:
      1. Tính stationary returns (pct_change) cho mỗi coin
      2. Lagged correlation screen (fast filter)
      3. Granger causality test (direction test)
      4. Xây dựng CoinCausalGraph
    """

    # Ngưỡng mặc định (conservative)
    MIN_CORRELATION: float = 0.20
    MAX_GRANGER_PVALUE: float = 0.10
    MIN_CONFIDENCE: float = 0.55

    def __init__(
        self,
        coins: Optional[List[str]] = None,
        max_lag: int = 12,
        min_correlation: float = 0.20,
        max_pvalue: float = 0.10,
        min_confidence: float = 0.55,
    ) -> None:
        self.coins = coins or DEFAULT_COINS
        self.max_lag = max_lag
        self.min_correlation = min_correlation
        self.max_pvalue = max_pvalue
        self.min_confidence = min_confidence

    # ── Public API ──────────────────────────────────────────────────────────

    def run(
        self,
        data: pd.DataFrame,
        price_col_suffix: str = "",
        skip_self_cluster: bool = False,
    ) -> CoinCausalGraph:
        """
        Chạy phân tích causal trên dữ liệu giá.

        Args:
            data: DataFrame với columns là tên coin (e.g., "BTC", "ETH").
                  Mỗi column chứa giá close (hoặc return) theo thời gian.
                  Cần ít nhất 100 rows để kết quả đáng tin cậy.
            price_col_suffix: Suffix của column name (e.g., "_close").
            skip_self_cluster: Bỏ qua các cặp cùng cluster nếu True.

        Returns:
            CoinCausalGraph với tất cả các cặp causal tìm được.
        """
        available_coins = self._resolve_coins(data, price_col_suffix)
        if len(available_coins) < 2:
            logger.warning("[CoinCausalFinder] Cần ít nhất 2 coins để phân tích")
            return CoinCausalGraph(coins=available_coins)

        logger.info(
            f"[CoinCausalFinder] Phân tích {len(available_coins)} coins: "
            f"{available_coins}"
        )

        # Compute stationary returns
        returns = self._compute_returns(data, available_coins, price_col_suffix)
        n_samples = len(returns)

        pairs: List[CoinPair] = []
        total_pairs = len(available_coins) * (len(available_coins) - 1)
        tested = 0

        for leader in available_coins:
            if leader not in returns.columns:
                continue
            for follower in available_coins:
                if follower == leader or follower not in returns.columns:
                    continue

                tested += 1
                pair = self._test_pair(
                    leader=leader,
                    follower=follower,
                    returns=returns,
                    skip_self_cluster=skip_self_cluster,
                )
                if pair is not None:
                    pairs.append(pair)

        # Sort by confidence desc
        pairs.sort(key=lambda p: p.confidence, reverse=True)

        graph = CoinCausalGraph(
            pairs=pairs,
            coins=available_coins,
            n_samples=n_samples,
        )
        logger.info(
            f"[CoinCausalFinder] ✓ {graph.summary()} "
            f"(tested {tested}/{total_pairs} directed pairs)"
        )
        return graph

    def save(self, graph: CoinCausalGraph, output_path: str) -> bool:
        """Lưu CoinCausalGraph ra file JSON."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(graph.to_json_dict(), f, indent=2, ensure_ascii=False)
            logger.info(
                f"[CoinCausalFinder] ✓ Saved {len(graph.pairs)} pairs to '{output_path}'"
            )
            return True
        except Exception as exc:
            logger.error(f"[CoinCausalFinder] Save failed: {exc}")
            return False

    # ── Data Helpers ────────────────────────────────────────────────────────

    def _resolve_coins(self, data: pd.DataFrame, suffix: str) -> List[str]:
        """Xác định các coin có trong data."""
        found = []
        for coin in self.coins:
            col = f"{coin}{suffix}" if suffix else coin
            if col in data.columns:
                found.append(coin)
            elif not suffix:
                # Try case-insensitive
                matches = [c for c in data.columns if c.upper() == coin.upper()]
                if matches:
                    found.append(coin)
        return found

    def _compute_returns(
        self,
        data: pd.DataFrame,
        coins: List[str],
        suffix: str,
    ) -> pd.DataFrame:
        """Tính stationary returns (pct_change) cho mỗi coin."""
        ret_dict = {}
        for coin in coins:
            col = f"{coin}{suffix}" if suffix else coin
            if col not in data.columns:
                # Try original
                col = next(
                    (c for c in data.columns if c.upper() == coin.upper()), None
                )
                if col is None:
                    continue

            series = pd.to_numeric(data[col], errors="coerce").dropna()
            # Nếu std lớn → price series → dùng pct_change
            # Nếu std nhỏ → đã là return/ratio → dùng as-is
            if series.std() > 0.5:
                ret = series.pct_change().replace([np.inf, -np.inf], np.nan)
            else:
                ret = series
            ret_dict[coin] = ret

        returns = pd.DataFrame(ret_dict)
        returns = returns.dropna(how="all")
        return returns

    # ── Core Test ───────────────────────────────────────────────────────────

    def _test_pair(
        self,
        leader: str,
        follower: str,
        returns: pd.DataFrame,
        skip_self_cluster: bool,
    ) -> Optional[CoinPair]:
        """Test quan hệ nhân quả leader → follower."""
        leader_cluster = COIN_TO_CLUSTER.get(leader, "Other")
        follower_cluster = COIN_TO_CLUSTER.get(follower, "Other")
        is_intra = leader_cluster == follower_cluster

        if skip_self_cluster and is_intra:
            return None

        leader_ret = returns[leader].dropna()
        follower_ret = returns[follower].dropna()

        if len(leader_ret) < 50 or len(follower_ret) < 50:
            return None

        # Step 1: Lagged correlation
        best_lag, best_corr = _lagged_correlation(
            leader_ret, follower_ret, self.max_lag
        )

        if abs(best_corr) < self.min_correlation:
            logger.debug(
                f"[CoinCausalFinder] {leader}→{follower}: "
                f"corr={best_corr:.3f} < {self.min_correlation} — rejected"
            )
            return None

        # Step 2: Granger causality
        is_granger, pvalue = _granger_test(
            leader_ret, follower_ret, lag=best_lag, significance=self.max_pvalue
        )

        if not is_granger:
            logger.debug(
                f"[CoinCausalFinder] {leader}→{follower}: "
                f"Granger p={pvalue:.3f} > {self.max_pvalue} — rejected"
            )
            return None

        # Step 3: Build pair
        effect = "positive" if best_corr > 0 else "negative"
        weight = min(1.0, abs(best_corr) * 1.2)
        confidence = min(0.95, (abs(best_corr) + (1.0 - pvalue) * 0.3) / 1.3)

        if confidence < self.min_confidence:
            return None

        pair = CoinPair(
            leader=leader,
            follower=follower,
            lag=best_lag,
            correlation=round(best_corr, 4),
            granger_pvalue=round(pvalue, 4),
            weight=round(weight, 3),
            confidence=round(confidence, 3),
            effect=effect,
            leader_cluster=leader_cluster,
            follower_cluster=follower_cluster,
            is_intra_cluster=is_intra,
        )

        logger.info(
            f"[CoinCausalFinder] ✓ {leader}→{follower}: "
            f"effect={effect}, corr={best_corr:+.3f}, lag={best_lag}, "
            f"confidence={confidence:.2f}, granger_p={pvalue:.3f}, "
            f"cluster={leader_cluster}→{follower_cluster}"
        )
        return pair

    # ── Demo Data ───────────────────────────────────────────────────────────

    @staticmethod
    def generate_demo_data(
        coins: Optional[List[str]] = None,
        n: int = 600,
        seed: int = 42,
    ) -> pd.DataFrame:
        """
        Sinh dữ liệu tổng hợp với ground-truth causal structure:
          BTC → ETH (lag=1, positive)
          BTC → SOL (lag=2, positive)
          ETH → LINK (lag=1, positive)
          BTC → DOGE (lag=3, positive, weak)
          ETH → MATIC (lag=1, positive)
        """
        coins = coins or ["BTC", "ETH", "SOL", "BNB", "LINK", "DOGE", "MATIC", "XRP"]
        rng = np.random.default_rng(seed)

        # BTC: random walk
        btc_ret = rng.normal(0.0005, 0.022, n)
        btc = 30000.0 * np.exp(np.cumsum(btc_ret))

        # ETH: follows BTC lag=1 + noise
        eth_ret = 0.80 * np.roll(btc_ret, 1) + rng.normal(0, 0.018, n)
        eth_ret[0] = rng.normal(0, 0.018)
        eth = 2000.0 * np.exp(np.cumsum(eth_ret))

        # SOL: follows BTC lag=2 + noise
        sol_ret = 0.65 * np.roll(btc_ret, 2) + rng.normal(0, 0.030, n)
        sol_ret[:2] = rng.normal(0, 0.030, 2)
        sol = 80.0 * np.exp(np.cumsum(sol_ret))

        # BNB: follows BTC lag=1, partial
        bnb_ret = 0.55 * np.roll(btc_ret, 1) + rng.normal(0, 0.020, n)
        bnb_ret[0] = rng.normal(0, 0.020)
        bnb = 250.0 * np.exp(np.cumsum(bnb_ret))

        # LINK: follows ETH lag=1
        link_ret = 0.60 * np.roll(eth_ret, 1) + rng.normal(0, 0.025, n)
        link_ret[0] = rng.normal(0, 0.025)
        link = 8.0 * np.exp(np.cumsum(link_ret))

        # DOGE: weak follow BTC lag=3 + high noise
        doge_ret = 0.35 * np.roll(btc_ret, 3) + rng.normal(0, 0.045, n)
        doge_ret[:3] = rng.normal(0, 0.045, 3)
        doge = 0.08 * np.exp(np.cumsum(doge_ret))

        # MATIC: follows ETH lag=1
        matic_ret = 0.58 * np.roll(eth_ret, 1) + rng.normal(0, 0.028, n)
        matic_ret[0] = rng.normal(0, 0.028)
        matic = 1.0 * np.exp(np.cumsum(matic_ret))

        # XRP: mostly independent with weak BTC correlation
        xrp_ret = 0.25 * np.roll(btc_ret, 1) + rng.normal(0, 0.030, n)
        xrp_ret[0] = rng.normal(0, 0.030)
        xrp = 0.5 * np.exp(np.cumsum(xrp_ret))

        price_map = {
            "BTC": btc, "ETH": eth, "SOL": sol, "BNB": bnb,
            "LINK": link, "DOGE": doge, "MATIC": matic, "XRP": xrp,
        }

        return pd.DataFrame({c: price_map[c] for c in coins if c in price_map})


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    coins_to_test = ["BTC", "ETH", "SOL", "BNB", "LINK", "DOGE", "MATIC", "XRP"]

    print("=" * 70)
    print("CoinCausalRelationFinder - Demo Run")
    print("=" * 70)

    # Generate synthetic data
    print(f"\n[1] Generating demo data for {coins_to_test}...")
    data = CoinCausalRelationFinder.generate_demo_data(coins=coins_to_test, n=600)
    print(f"    Data shape: {data.shape}")
    print(f"    Coins: {list(data.columns)}")

    # Run finder
    print("\n[2] Running causal discovery...")
    finder = CoinCausalRelationFinder(coins=coins_to_test, max_lag=8)
    graph = finder.run(data)

    print(f"\n[3] Results:")
    print(f"    {graph.summary()}")
    print(f"\n    Causal pairs found ({len(graph.pairs)}):")
    for pair in graph.pairs:
        intra_tag = "[intra]" if pair.is_intra_cluster else "[inter]"
        print(
            f"      {intra_tag} {pair.leader:6s} -> {pair.follower:6s} | "
            f"lag={pair.lag:2d} | corr={pair.correlation:+.3f} | "
            f"conf={pair.confidence:.2f} | {pair.leader_cluster}->{pair.follower_cluster}"
        )

    # Show adjacency
    print("\n    Leader -> Followers:")
    adj = graph.get_adjacency()
    for leader, followers in adj.items():
        print(f"      {leader} -> {followers}")

    # Save to file
    out_path = "data/causal_coin_graph.json"
    print(f"\n[4] Saving to '{out_path}'...")
    saved = finder.save(graph, out_path)
    print(f"    {'[OK] Saved successfully' if saved else '[FAIL] Save failed'}")
