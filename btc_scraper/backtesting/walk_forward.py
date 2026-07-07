from typing import Dict, Any, List, Tuple
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class WalkForwardValidator:
    """
    Splits historical signal and feature dataset into rolling train-test windows to validate strategy stability.
    """
    def __init__(self, config_wf: Dict[str, Any]):
        self.train_months = config_wf.get("train_months", 6)
        self.test_months = config_wf.get("test_months", 1)
        self.step_months = config_wf.get("step_months", 1)

    def generate_windows(self, df: pd.DataFrame, time_col: str = "entry_time") -> List[Tuple[datetime, datetime, datetime, datetime]]:
        """
        Generates datetime boundaries for each window.
        Returns: List of tuples (train_start, train_end, test_start, test_end)
        """
        if df.empty:
            return []
            
        times = pd.to_datetime(df[time_col])
        start_date = times.min().to_pydatetime()
        end_date = times.max().to_pydatetime()
        
        windows = []
        current_train_start = start_date
        
        while True:
            # Calculate train end: current_train_start + train_months
            # Using timedelta approximation (30.4 days per month)
            train_end = current_train_start + timedelta(days=int(self.train_months * 30.4))
            test_start = train_end
            test_end = test_start + timedelta(days=int(self.test_months * 30.4))
            
            if test_end > end_date:
                # Last window boundary adjustment
                if test_start < end_date:
                    windows.append((current_train_start, train_end, test_start, end_date))
                break
                
            windows.append((current_train_start, train_end, test_start, test_end))
            
            # Step forward
            current_train_start = current_train_start + timedelta(days=int(self.step_months * 30.4))
            
        return windows

    def run_validation(
        self,
        df: pd.DataFrame,
        time_col: str = "entry_time",
        label_col: str = "meta_label",
        prediction_col: str = "signal_score"
    ) -> List[Dict[str, Any]]:
        """
        Performs walk forward evaluation by slicing the dataset and calculating metrics.
        """
        windows = self.generate_windows(df, time_col)
        df = df.copy()
        df[time_col] = pd.to_datetime(df[time_col])
        
        results = []
        
        for idx, (tr_start, tr_end, ts_start, ts_end) in enumerate(windows):
            # Localize times for comparisons if DataFrame is timezone aware
            if df[time_col].dt.tz is not None:
                import pytz
                tr_start = pd.Timestamp(tr_start).tz_localize('UTC')
                tr_end = pd.Timestamp(tr_end).tz_localize('UTC')
                ts_start = pd.Timestamp(ts_start).tz_localize('UTC')
                ts_end = pd.Timestamp(ts_end).tz_localize('UTC')
                
            train_mask = (df[time_col] >= tr_start) & (df[time_col] < tr_end)
            test_mask = (df[time_col] >= ts_start) & (df[time_col] <= ts_end)
            
            train_df = df[train_mask]
            test_df = df[test_mask]
            
            n_train = len(train_df)
            n_test = len(test_df)
            
            if n_train == 0 or n_test == 0:
                continue
                
            # Perform basic out-of-sample evaluation metrics
            # If label_col is present and prediction_col is present, calculate simple win-rate/profit-factor
            # We assume trades occur on the test split when prediction_col is high (BUY) or low (SELL)
            test_trades = test_df[test_df[prediction_col] >= 70.0]
            n_trades = len(test_trades)
            
            if n_trades > 0:
                # In test_trades, if label_col (ground truth) is 1.0 -> WIN, else LOSS
                wins = len(test_trades[test_trades[label_col] == 1.0])
                win_rate = wins / n_trades
                
                # Mock return calculation
                returns = test_trades.apply(lambda r: 0.02 if r[label_col] == 1.0 else -0.015, axis=1)
                total_return = float(returns.sum())
                
                # Profit factor
                gross_profit = wins * 0.02
                gross_loss = (n_trades - wins) * 0.015
                profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.0
            else:
                win_rate = 0.0
                total_return = 0.0
                profit_factor = 0.0
                
            results.append({
                "window_id": idx + 1,
                "train_start": tr_start.strftime("%Y-%m-%d") if hasattr(tr_start, "strftime") else str(tr_start),
                "train_end": tr_end.strftime("%Y-%m-%d") if hasattr(tr_end, "strftime") else str(tr_end),
                "test_start": ts_start.strftime("%Y-%m-%d") if hasattr(ts_start, "strftime") else str(ts_start),
                "test_end": ts_end.strftime("%Y-%m-%d") if hasattr(ts_end, "strftime") else str(ts_end),
                "n_train": n_train,
                "n_test": n_test,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "total_return": total_return
            })
            
        return results
