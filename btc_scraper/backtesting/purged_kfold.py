import numpy as np
import pandas as pd
from typing import Generator, Tuple, List

class PurgedKFold:
    """
    Implements Marcos Lopez de Prado's Purged K-Fold Cross Validation with Embargo.
    Prevents leakage by removing training samples that overlap with or immediately follow test samples.
    """
    def __init__(self, n_splits: int = 5, embargo_pct: float = 0.01):
        self.n_splits = n_splits
        self.embargo_pct = embargo_pct

    def split(
        self,
        df: pd.DataFrame,
        t1_col: str = "entry_time",
        t2_col: str = "exit_time"
    ) -> Generator[Tuple[np.ndarray, np.ndarray], None, None]:
        """
        Yields (train_indices, test_indices) for cross-validation.
        
        Args:
            df: DataFrame containing sample timestamps.
            t1_col: Start time of the label evaluation.
            t2_col: End time of the label evaluation.
        """
        n_samples = len(df)
        indices = np.arange(n_samples)
        
        # Sort by t1 to ensure chronological order for split boundaries
        sorted_df = df.copy()
        sorted_df["_orig_idx"] = indices
        sorted_df = sorted_df.sort_values(t1_col)
        
        t1 = pd.to_datetime(sorted_df[t1_col]).values
        # If exit_time is missing, fallback to entry_time + 12h
        if t2_col in sorted_df.columns:
            t2 = pd.to_datetime(sorted_df[t2_col]).values
        else:
            t2 = t1 + np.timedelta64(12, 'h')
            
        test_bounds = np.linspace(0, n_samples, self.n_splits + 1, dtype=int)
        
        for i in range(self.n_splits):
            test_start, test_end = test_bounds[i], test_bounds[i+1]
            test_indices = sorted_df["_orig_idx"].iloc[test_start:test_end].values
            
            test_t1_min = t1[test_start]
            test_t2_max = t2[test_end - 1]
            
            # Find train indices
            # Baseline train includes everything not in test
            train_mask = np.ones(n_samples, dtype=bool)
            train_mask[test_start:test_end] = False
            
            # Purging: remove samples that overlap with test fold
            # Overlap occurs when: train_start <= test_end AND train_end >= test_start
            overlap_mask = (t1 <= test_t2_max) & (t2 >= test_t1_min)
            train_mask[overlap_mask] = False
            
            # Embargo: remove samples starting immediately after test fold
            embargo_offset = int(n_samples * self.embargo_pct)
            embargo_limit_idx = min(test_end + embargo_offset, n_samples)
            if embargo_limit_idx > test_end:
                embargo_t1_limit = t1[embargo_limit_idx - 1]
                embargo_mask = (t1 > test_t2_max) & (t1 <= embargo_t1_limit)
                train_mask[embargo_mask] = False
                
            train_indices = sorted_df["_orig_idx"].iloc[train_mask].values
            
            yield train_indices, test_indices
class PurgedKFoldSplit:
    pass
