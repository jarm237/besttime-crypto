import os
import json
import time
from typing import List, Dict, Any

TRACKED_SIGNALS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "tracked_signals.json")
MAX_AGE_MINUTES = 90  # Keep signals up to 90 minutes

class SignalTracker:
    def __init__(self, filepath: str = TRACKED_SIGNALS_FILE):
        self.filepath = filepath
        self.signals = self._load_signals()
        
    def _load_signals(self) -> Dict[str, List[Dict[str, Any]]]:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[SignalTracker] Error loading tracked signals: {e}")
        return {}
        
    def _save_signals(self):
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self.signals, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[SignalTracker] Error saving tracked signals: {e}")

    def register_signal(self, coin: str, signal_time: str, signal: str, entry: float, tp_sl: dict, reason: str):
        """
        Registers a new valid signal to track.
        Avoids duplicates if a signal with the same timestamp and type already exists for the coin.
        """
        if coin not in self.signals:
            self.signals[coin] = []
            
        # Check duplicate by exact time
        for s in self.signals[coin]:
            if s.get("time") == signal_time:
                return
                
        # Register new signal
        self.signals[coin].append({
            "time": signal_time,
            "signal": signal,
            "entry": entry,
            "tp_sl": tp_sl,
            "reason": reason,
            "status": "Running (Van con hieu luc)",
            "age_minutes": 0,
            "created_at_ts": time.time()
        })
        self._save_signals()

    def evaluate_signals(self, coin: str, current_close: float) -> List[Dict[str, Any]]:
        """
        Evaluates active signals for a given coin against the current close price.
        Returns the list of currently tracked signals for this coin.
        """
        if coin not in self.signals:
            return []
            
        current_ts = time.time()
        updated_signals = []
        changed = False
        
        for s in self.signals[coin]:
            # Update age
            created_at = s.get("created_at_ts", current_ts)
            age_mins = int((current_ts - created_at) / 60.0)
            if s.get("age_minutes") != age_mins:
                s["age_minutes"] = age_mins
                changed = True
                
            # If age > MAX_AGE_MINUTES, prune it
            if age_mins > MAX_AGE_MINUTES:
                changed = True
                continue
                
            status = s.get("status", "Running (Van con hieu luc)")
            
            # Evaluate only if still running
            if "Running" in status:
                sig_type = s.get("signal", "")
                sl_level = s.get("tp_sl", {}).get("sl", 0.0)
                tp1_level = s.get("tp_sl", {}).get("tp1", 0.0)
                tp2_level = s.get("tp_sl", {}).get("tp2", 0.0)
                
                new_status = status
                if "BUY" in sig_type or "BULL" in sig_type:
                    if sl_level > 0 and current_close <= sl_level:
                        new_status = "Hit SL (Da can SL)"
                    elif tp2_level > 0 and current_close >= tp2_level:
                        new_status = "Hit TP2 (Da dat TP2)"
                    elif tp1_level > 0 and current_close >= tp1_level:
                        new_status = "Hit TP1 (Da dat TP1)"
                elif "SELL" in sig_type or "BEAR" in sig_type or "SHORT" in sig_type:
                    if sl_level > 0 and current_close >= sl_level:
                        new_status = "Hit SL (Da can SL)"
                    elif tp2_level > 0 and current_close <= tp2_level:
                        new_status = "Hit TP2 (Da dat TP2)"
                    elif tp1_level > 0 and current_close <= tp1_level:
                        new_status = "Hit TP1 (Da dat TP1)"
                
                if new_status != status:
                    s["status"] = new_status
                    changed = True
                    
            updated_signals.append(s)
            
        # Update the list
        if len(self.signals[coin]) != len(updated_signals) or changed:
            self.signals[coin] = updated_signals
            self._save_signals()
            
        return self.signals[coin]

# Global instance
signal_tracker = SignalTracker()
