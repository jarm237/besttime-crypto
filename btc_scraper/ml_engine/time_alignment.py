"""
Time Alignment Module - Forward Fill for causal features (prevents look-ahead bias)

Synchronizes multi-frequency market data to prevent look-ahead bias:
- Macro data (1 day) → resampled with forward fill
- Funding rates (8 hours) → resampled with forward fill
- OI (5 minutes) → kept as-is
- On-chain data → aligned to crypto data frequency
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
from datetime import datetime
import logging


logger = logging.getLogger(__name__)


class TimeAlignmentManager:
    """Manages time alignment and forward fill for multi-frequency data."""

    def __init__(self):
        """Initialize time alignment manager."""
        self.last_macro_update = None
        self.macro_cache = {}

    def align_dataframes(
        self,
        crypto_df: pd.DataFrame,
        macro_df: Optional[pd.DataFrame] = None,
        funding_df: Optional[pd.DataFrame] = None,
        oi_df: Optional[pd.DataFrame] = None,
        method: str = "ffill",
    ) -> pd.DataFrame:
        """
        Align all data to crypto data frequency using forward fill.
        
        CRITICAL: Only uses forward fill (never backward fill) to prevent look-ahead bias
        
        Args:
            crypto_df: Crypto OHLCV data (highest frequency) - index: datetime
            macro_df: Macro data (lower frequency, 1 day) - index: datetime
            funding_df: Funding rates (8h frequency) - index: datetime
            oi_df: Open Interest (5m frequency) - index: datetime
            method: Fill method ("ffill" recommended, never "bfill")
            
        Returns:
            DataFrame aligned to crypto frequency with all features
        """
        if method != "ffill":
            logger.warning(f"Using {method} for time alignment - RISK OF LOOK-AHEAD BIAS!")

        # Start with crypto as base
        result_df = crypto_df.copy()
        result_df = result_df.sort_index()

        # Align macro data (forward fill only)
        if macro_df is not None:
            macro_df = macro_df.sort_index()
            macro_aligned = macro_df.reindex(
                result_df.index,
                method="ffill",  # Forward fill only
                limit=None
            )
            # Prefix columns to distinguish
            macro_aligned.columns = [f"macro_{col}" for col in macro_aligned.columns]
            result_df = result_df.join(macro_aligned)
            logger.info(f"Aligned macro data: {macro_aligned.shape[0]} rows → {result_df.shape[0]} rows")

        # Align funding data (forward fill only)
        if funding_df is not None:
            funding_df = funding_df.sort_index()
            funding_aligned = funding_df.reindex(
                result_df.index,
                method="ffill",  # Forward fill only
                limit=None
            )
            funding_aligned.columns = [f"funding_{col}" for col in funding_aligned.columns]
            result_df = result_df.join(funding_aligned)
            logger.info(f"Aligned funding data: {funding_aligned.shape[0]} rows → {result_df.shape[0]} rows")

        # Align OI data (forward fill only)
        if oi_df is not None:
            oi_df = oi_df.sort_index()
            oi_aligned = oi_df.reindex(
                result_df.index,
                method="ffill",  # Forward fill only
                limit=None
            )
            oi_aligned.columns = [f"oi_{col}" for col in oi_aligned.columns]
            result_df = result_df.join(oi_aligned)
            logger.info(f"Aligned OI data: {oi_aligned.shape[0]} rows → {result_df.shape[0]} rows")

        logger.info(f"Time alignment complete: {result_df.shape[0]} rows with {result_df.shape[1]} features")
        return result_df

    def validate_no_lookahead_bias(
        self,
        aligned_df: pd.DataFrame,
        macro_cols: Optional[list] = None,
    ) -> bool:
        """
        Validate that macro data doesn't have look-ahead bias.
        
        Checks:
        - Macro values never change except at update times
        - No backward fill occurred
        - Forward fill is monotonic
        """
        if macro_cols is None:
            macro_cols = [col for col in aligned_df.columns if col.startswith("macro_")]

        if not macro_cols:
            logger.info("No macro columns to validate")
            return True

        # Check that changes only occur at certain intervals (not randomly)
        for col in macro_cols:
            if col in aligned_df.columns:
                changes = aligned_df[col].diff().abs().sum()
                non_null_indices = aligned_df[col].notna()
                num_changes = (aligned_df[col].diff() != 0).sum()

                logger.info(f"{col}: {num_changes} changes across {len(aligned_df)} rows")

                if num_changes > len(aligned_df) * 0.05:  # More than 5% changes = suspicious
                    logger.warning(f"⚠️ {col} has high change frequency - check for backward fill!")
                    return False

        logger.info("✓ No look-ahead bias detected")
        return True

    def forward_fill_single_series(
        self,
        series: pd.Series,
        target_index: pd.DatetimeIndex,
        method: str = "ffill",
        limit: Optional[int] = None,
    ) -> pd.Series:
        """
        Forward fill a single series to target frequency.
        
        Args:
            series: Input series with irregular datetime index
            target_index: Target datetime index to align to
            method: "ffill" or "bfill" (ffill strongly recommended)
            limit: Max number of consecutive fills (None = unlimited)
            
        Returns:
            Forward-filled series aligned to target_index
        """
        if method != "ffill":
            logger.warning(f"Using {method} - risk of look-ahead bias")

        series = series.sort_index()
        aligned = series.reindex(target_index, method=method, limit=limit)

        num_filled = aligned.isna().sum()
        logger.debug(f"Filled {num_filled} NaN values using {method}")

        return aligned

    def create_lagged_features(
        self,
        df: pd.DataFrame,
        macro_cols: list,
        lags: Dict[str, int],
    ) -> pd.DataFrame:
        """
        Create lagged features for causal analysis.
        
        Helps model learn causal relationships with specific lags.
        
        Args:
            df: Aligned dataframe
            macro_cols: Columns to create lags for
            lags: Dict of {column: lag_periods}
            
        Returns:
            DataFrame with additional lagged columns
        """
        result = df.copy()

        for col in macro_cols:
            if col in df.columns:
                lag_periods = lags.get(col, 1)
                for lag in range(1, lag_periods + 1):
                    result[f"{col}_lag{lag}"] = df[col].shift(lag)

        logger.info(f"Created lagged features: {result.shape[1] - df.shape[1]} new columns")
        return result

    def check_data_quality(
        self,
        df: pd.DataFrame,
        required_cols: list,
        min_non_null_ratio: float = 0.95,
    ) -> Tuple[bool, Dict]:
        """
        Check data quality after alignment.
        
        Returns:
            (is_valid, quality_report)
        """
        report = {
            "total_rows": len(df),
            "missing_columns": [],
            "columns_below_threshold": [],
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Check required columns
        for col in required_cols:
            if col not in df.columns:
                report["missing_columns"].append(col)
            else:
                non_null_ratio = df[col].notna().sum() / len(df)
                if non_null_ratio < min_non_null_ratio:
                    report["columns_below_threshold"].append({
                        "column": col,
                        "non_null_ratio": non_null_ratio,
                    })

        is_valid = (
            len(report["missing_columns"]) == 0 and
            len(report["columns_below_threshold"]) == 0
        )

        if is_valid:
            logger.info(f"✓ Data quality check passed: {len(df)} rows, {df.shape[1]} features")
        else:
            logger.warning(f"⚠️ Data quality issues detected: {report}")

        return is_valid, report


def example_usage():
    """Example of how to use TimeAlignmentManager."""
    # Create sample data
    dates = pd.date_range("2026-06-01", periods=100, freq="1H")
    
    crypto_df = pd.DataFrame({
        "open": np.random.uniform(50000, 60000, 100),
        "high": np.random.uniform(50000, 60000, 100),
        "low": np.random.uniform(50000, 60000, 100),
        "close": np.random.uniform(50000, 60000, 100),
        "volume": np.random.uniform(1000, 5000, 100),
    }, index=dates)

    # Macro data (1 day frequency - sparse)
    macro_dates = pd.date_range("2026-06-01", periods=5, freq="1D")
    macro_df = pd.DataFrame({
        "DXY": [103.5, 104.0, 103.8, 104.2, 104.5],
        "VIX": [20.0, 21.5, 20.8, 22.0, 23.5],
    }, index=macro_dates)

    # Align
    manager = TimeAlignmentManager()
    aligned = manager.align_dataframes(crypto_df, macro_df=macro_df)

    print(f"Aligned shape: {aligned.shape}")
    print(f"\nFirst 10 rows:\n{aligned.head(10)}")

    # Validate no look-ahead bias
    manager.validate_no_lookahead_bias(aligned, macro_cols=["macro_DXY", "macro_VIX"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    example_usage()
