from typing import Dict, Any
from btc_scraper.backtesting.config import APPROVAL_RULES

class ReportBuilder:
    """
    Validates backtest metrics against the institutional strategy approval gate.
    """
    
    @staticmethod
    def check_approval_gate(
        metrics: Dict[str, Any],
        mc_metrics: Dict[str, Any],
        regime_metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validates strategy statistics against strict approval rules.
        """
        rules = APPROVAL_RULES
        
        # 1. Sharpe
        sharpe = metrics.get("sharpe", 0.0)
        sharpe_ok = sharpe >= rules["min_sharpe"]
        
        # 2. Profit factor
        pf = metrics.get("profit_factor", 0.0)
        pf_ok = pf >= rules["min_profit_factor"]
        
        # 3. Max Drawdown
        max_dd = metrics.get("max_drawdown", 0.0)
        dd_ok = max_dd <= rules["max_drawdown"]
        
        # 4. Min trades
        n_trades = metrics.get("n_trades", 0)
        trades_ok = n_trades >= rules["min_trades"]
        
        # 5. Cost Drag
        cost_drag = metrics.get("cost_drag", 0.0)
        cost_drag_ok = cost_drag <= rules["max_cost_drag_pct_of_gross"]
        
        # 6. Monte Carlo Probability of Loss
        mc_loss = mc_metrics.get("probability_of_loss", 1.0)
        mc_loss_ok = mc_loss <= rules["max_probability_of_loss_mc"]
        
        # 7. Monte Carlo Probability of Drawdown > 10%
        mc_dd = mc_metrics.get("probability_max_dd_gt_10pct", 1.0)
        mc_dd_ok = mc_dd <= rules["max_probability_dd_gt_10pct"]
        
        # 8. Regimes count
        pos_regimes = 0
        for reg_name, reg_stats in regime_metrics.items():
            if reg_stats.get("total_return", 0.0) > 0.0:
                pos_regimes += 1
        regimes_ok = pos_regimes >= rules["positive_in_at_least_n_regimes"]
        
        passed = (
            sharpe_ok and pf_ok and dd_ok and trades_ok and 
            cost_drag_ok and mc_loss_ok and mc_dd_ok and regimes_ok
        )
        
        return {
            "passed": bool(passed),
            "rules": {
                "sharpe": {"val": sharpe, "target": f">={rules['min_sharpe']}", "ok": bool(sharpe_ok)},
                "profit_factor": {"val": pf, "target": f">={rules['min_profit_factor']}", "ok": bool(pf_ok)},
                "max_drawdown": {"val": max_dd, "target": f"<={rules['max_drawdown']}", "ok": bool(dd_ok)},
                "min_trades": {"val": n_trades, "target": f">={rules['min_trades']}", "ok": bool(trades_ok)},
                "cost_drag": {"val": cost_drag, "target": f"<={rules['max_cost_drag_pct_of_gross']}", "ok": bool(cost_drag_ok)},
                "mc_prob_loss": {"val": mc_loss, "target": f"<={rules['max_probability_of_loss_mc']}", "ok": bool(mc_loss_ok)},
                "mc_prob_dd_10pct": {"val": mc_dd, "target": f"<={rules['max_probability_dd_gt_10pct']}", "ok": bool(mc_dd_ok)},
                "regimes_positive": {"val": pos_regimes, "target": f">={rules['positive_in_at_least_n_regimes']}", "ok": bool(regimes_ok)}
            }
        }
