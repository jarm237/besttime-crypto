"""
Multi-Agent AI Platform — Định nghĩa các Agent chuyên biệt và Orchestrator điều phối.
"""

import os
import time
from typing import Dict, Any, List
from rich.console import Console

from btc_scraper.analysis import analyze_market
from btc_scraper.core.config import COINS
from btc_scraper.trading.portfolio_manager import PortfolioManager
from btc_scraper.trading import position_tracker

console = Console()

class BaseAgent:
    """
    Lớp cơ sở cho tất cả các Agent trong hệ thống.
    """
    def __init__(self, name: str):
        self.name = name

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Thực thi nhiệm vụ của Agent trên context chung và trả về context đã được cập nhật.
        """
        raise NotImplementedError("Mỗi Agent phải tự triển khai hàm run().")

class MarketAnalystAgent(BaseAgent):
    """
    MarketAnalystAgent: Cào dữ liệu, tính chỉ báo, phát hiện regime thị trường và xu hướng đa khung thời gian.
    """
    def __init__(self):
        super().__init__("MarketAnalyst")

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        raw_candles = context["raw_candles"]
        mtf_candles = context.get("mtf_candles", {})

        analysis_results = {}
        mtf_analysis_results = {}
        for coin in COINS:
            # 1. Phân tích nến 15m
            candles_15m = raw_candles.get(coin, [])
            if not candles_15m or "error" in candles_15m[0]:
                continue
            ana = analyze_market(candles_15m, coin)
            ana["close"] = candles_15m[-1]["close"]
            analysis_results[f"{coin}:Binance"] = ana

            # 2. Phân tích đa khung thời gian (MTF)
            coin_mtf = mtf_candles.get(coin, {})
            mtf_ana_dict = {}
            for tf in ["1h", "4h", "1d"]:
                tf_candles = coin_mtf.get(tf, [])
                if tf_candles and "error" not in tf_candles[0]:
                    tf_ana = analyze_market(tf_candles, coin)
                    tf_ana["close"] = tf_candles[-1]["close"]
                    mtf_ana_dict[tf] = tf_ana
            
            mtf_analysis_results[coin] = mtf_ana_dict
            
            # Gắn HTF Trend
            from btc_scraper.analysis.htf_utils import summarize_htf_trend, format_htf_details
            htf_trend = summarize_htf_trend(mtf_ana_dict)
            htf_details = format_htf_details(mtf_ana_dict)
            analysis_results[f"{coin}:Binance"]["htf_trend"] = htf_trend
            analysis_results[f"{coin}:Binance"]["htf_details"] = htf_details

            # Per-TF direction features cho MTF Confluence Filter
            for tf in ["1h", "4h", "1d"]:
                tf_data = mtf_ana_dict.get(tf, {})
                ema9 = float(tf_data.get("ema9") or 0.0)
                ema21 = float(tf_data.get("ema21") or 0.0)
                close_tf = float(tf_data.get("close") or 0.0)
                sma50 = float(tf_data.get("sma50") or 0.0)
                chandelier = str(tf_data.get("chandelier") or "").upper()
                if ema9 > ema21 and chandelier == "BULL" and close_tf > sma50:
                    bull_val = 1
                elif ema9 < ema21 and chandelier == "BEAR" and close_tf < sma50:
                    bull_val = -1
                else:
                    bull_val = 0
                tf_key = f"tf_{tf}_bull"
                analysis_results[f"{coin}:Binance"][tf_key] = bull_val

        context["analysis"] = analysis_results
        context["mtf_analysis"] = mtf_analysis_results
        return context

class SignalGeneratorAgent(BaseAgent):
    """
    SignalGeneratorAgent: Chấm điểm tín hiệu qua Meta Model, lọc nhiễu và gán thông số thô.
    """
    def __init__(self):
        super().__init__("SignalGenerator")

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        analysis = context["analysis"]
        from btc_scraper.ml_engine.signal_score import evaluate_signal_score
        from btc_scraper.ml_engine.causal_context_bridge import enhance_signal_with_causal_context
        
        signals_info = []
        for key, ana in list(analysis.items()):
            coin = key.split(":")[0]
            ana.setdefault("coin", coin)
            ana.setdefault("symbol", f"{coin}USDT")
            # Chấm điểm và dự báo xác suất thắng
            sig_score = evaluate_signal_score(ana)
            ana["signal_score"] = sig_score

            # Phase C: Tích hợp Causal Context (alpha=0.0 = safe mode, chỉ rules)
            try:
                causal_enhanced = enhance_signal_with_causal_context(
                    ana=ana,
                    analysis_info={**ana, **sig_score},
                    alpha=float(os.environ.get("CAUSAL_ALPHA", "0.0")),
                )
                if causal_enhanced and not causal_enhanced.get("error"):
                    ana["causal_decision"] = causal_enhanced
                    risk_level = causal_enhanced.get("context_risk_level", "LOW")
                    ana["causal_context_risk"] = risk_level
                    ana["causal_context_skipped"] = causal_enhanced.get("context_skipped", False)

                    # Safe gate: only override to NEUTRAL for CRITICAL risk.
                    if risk_level == "CRITICAL" and sig_score.get("action") in ("BUY", "SELL"):
                        sig_score["action"] = "NEUTRAL"
                        sig_score["causal_overridden"] = True
                        console.print(f"[bold red][CausalGate] {coin}: Action → NEUTRAL (CRITICAL risk)[/bold red]")
                    elif risk_level in ("HIGH", "MEDIUM") and sig_score.get("action") in ("BUY", "SELL"):
                        sig_score["causal_warning"] = True
                        sig_score["causal_risk_level"] = risk_level
                        console.print(f"[yellow][CausalGate] {coin}: Elevated risk ({risk_level}) — warning only[/yellow]")
            except Exception as _ce:
                pass  # Graceful degradation: causal context không ảnh hưởng core flow
            
            # Đọc cutoff và thông tin Kelly mặc định
            meta_conf = sig_score.get("meta_confidence", 0.5)
            kelly_frac = sig_score.get("kelly_fraction", 0.0)
            action = sig_score.get("action", "NEUTRAL")
            
            signals_info.append({
                "coin": coin,
                "action": action,
                "meta_confidence": meta_conf,
                "kelly_fraction": kelly_frac,
                "close": ana.get("close", 0.0),
                "atr": ana.get("atr", 0.0),
                "signal": ana.get("signal", "")
            })
            
        context["signals_info"] = signals_info
        return context

class RiskManagerAgent(BaseAgent):
    """
    RiskManagerAgent: Áp dụng các luật quản lý rủi ro tài khoản, drawdown limits và consecutive losses.
    """
    def __init__(self):
        super().__init__("RiskManager")

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        from btc_scraper.trading.risk_manager import calculate_risk_metrics
        
        # Tính toán các chỉ số rủi ro dựa trên closed_positions.json
        risk_metrics = calculate_risk_metrics()
        context["risk_metrics"] = risk_metrics
        
        # Nếu bị block do drawdown vượt mức, hạ cấp tất cả tín hiệu về NEUTRAL
        if risk_metrics.get("blocked", False):
            console.print(f"[bold red][RiskManager] HỆ THỐNG GIAO DỊCH BỊ KHÓA do Drawdown vượt 10%! (Drawdown hiện tại: {risk_metrics.get('drawdown_pct'):.2f}%)[/bold red]")
            for s in context["signals_info"]:
                s["action"] = "NEUTRAL"
                
        # Áp dụng risk multiplier nếu gặp chuỗi thua
        risk_mult = risk_metrics.get("risk_multiplier", 1.0)
        if risk_mult < 1.0:
            console.print(f"[bold yellow][RiskManager] Áp dụng Risk Multiplier {risk_mult} do chuỗi thua liên tiếp ({risk_metrics.get('consecutive_losses')} lệnh)[/bold yellow]")
            for s in context["signals_info"]:
                s["kelly_fraction"] = float(s["kelly_fraction"]) * risk_mult

        return context

class PortfolioManagerAgent(BaseAgent):
    """
    PortfolioManagerAgent: Phân bổ vốn tối ưu giữa các tín hiệu đồng thời dựa trên ma trận tương quan.
    """
    def __init__(self):
        super().__init__("PortfolioManager")
        # Sử dụng Mean-Variance Optimization làm mặc định
        self.pm = PortfolioManager(method="MVO", risk_aversion=2.0, max_weight=0.30)

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        signals_info = context["signals_info"]
        raw_candles = context["raw_candles"]
        
        # Chỉ chạy phân bổ nếu có tối thiểu 2 tín hiệu trở lên
        active_sigs = [s for s in signals_info if s["action"] in ("BUY", "SELL")]
        
        if len(active_sigs) >= 2:
            console.print(f"[bold cyan][PortfolioManager] Tìm thấy {len(active_sigs)} tín hiệu đồng thời. Bắt đầu tối ưu danh mục (MVO)...[/bold cyan]")
            weights = self.pm.allocate_weights(signals_info, raw_candles)
            
            # Ghi đè tỷ lệ phân bổ vốn tối ưu vào kelly_fraction
            for s in signals_info:
                coin = s["coin"]
                if coin in weights:
                    s["portfolio_weight"] = weights[coin]
                    s["kelly_fraction"] = weights[coin]  # Ghi đè kelly_fraction để auto_trader sử dụng
                    console.print(f"  ↳ Allocation {coin}: {weights[coin]*100:.2f}% vốn")
        else:
            # Nếu chỉ có 1 tín hiệu, gán portfolio_weight bằng kelly_fraction hiện tại
            for s in signals_info:
                s["portfolio_weight"] = s["kelly_fraction"]
                
        return context

class RLExitAgent(BaseAgent):
    """
    RLExitAgent: Sử dụng Agent Học tăng cường để đề xuất exit động cho các vị thế đang mở.
    """
    def __init__(self):
        super().__init__("RLExit")
        self.model = None
        self._load_rl_model()

    def _load_rl_model(self):
        try:
            from stable_baselines3 import PPO
            import glob
            # Tìm file model ppo mới nhất trong logs/rl_models/
            models = glob.glob("logs/rl_models/rl_exit_ppo_*.zip")
            if not models:
                # Fallback tìm best_model.zip
                models = glob.glob("logs/rl_models/best_model.zip")
                
            if models:
                latest_model = max(models)
                self.model = PPO.load(latest_model)
                console.print(f"[bold green]  [RLExitAgent] Loaded RL Model: {os.path.basename(latest_model)}[/bold green]")
        except Exception as e:
            console.print(f"[dim red]  [RLExitAgent] Không thể load model RL exit: {e}[/dim red]")

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        # Tác nhân RL đóng vai trò giám sát các vị thế đang mở và đưa ra gợi ý nâng cao
        # (Chi tiết logic đã được tích hợp qua position_tracker.py và shadow log)
        context["rl_model_loaded"] = self.model is not None
        return context

class ExecutionAgent(BaseAgent):
    """
    ExecutionAgent: Thực thi giao dịch CCXT và quản lý ghi nhận nhật ký giao dịch.
    """
    def __init__(self):
        super().__init__("Execution")

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        analysis = context["analysis"]
        mtf_analysis = context.get("mtf_analysis")
        
        # 1. Chạy Auto Trader (CCXT)
        try:
            from btc_scraper.trading.auto_trader import auto_trader
            await auto_trader.evaluate_and_trade(analysis, mtf_analysis=mtf_analysis)
        except Exception as e:
            console.print(f"[dim red][ExecutionAgent] Lỗi giao dịch CCXT: {e}[/dim red]")
            
        # 2. Phase D: Counterfactual analysis cho lệnh thua gần nhất
        try:
            import json as _json, os as _os
            from btc_scraper.ml_engine.causal_context_bridge import build_world_state_from_ana
            from btc_scraper.ml_engine.counterfactual_engine import CounterfactualEngine
            from btc_scraper.trading import position_tracker

            # Lấy 10 lệnh đã đóng gần nhất từ performance summary
            perf = position_tracker.get_performance_summary("ALL")
            closed_trades = perf.get("trades", []) if isinstance(perf, dict) else []
            # Chỉ xử lý các lệnh thua gần nhất (pnl_pct < -0.5%)
            losing_trades = [
                t for t in closed_trades[-10:]
                if isinstance(t, dict) and float(t.get("pnl_pct") or 0) < -0.5
            ]

            if losing_trades:
                cf_engine = CounterfactualEngine()
                cf_logs = []
                log_path = _os.path.join("logs", "counterfactual_log.json")
                if _os.path.exists(log_path):
                    with open(log_path, encoding="utf-8") as _f:
                        cf_logs = _json.load(_f)

                for trade in losing_trades[-3:]:   # Tối đa 3 lệnh/chu kỳ để tránh overhead
                    coin = trade.get("coin", "BTC")
                    ana = analysis.get(f"{coin}:Binance", {})
                    base_state = build_world_state_from_ana(ana)
                    if base_state is None:
                        continue
                    try:
                        cf_result = cf_engine.analyze_trade(trade, base_state)
                        cf_logs.append(cf_result)
                    except Exception:
                        pass

                # Giữ tối đa 200 bản ghi gần nhất
                _os.makedirs("logs", exist_ok=True)
                with open(log_path, "w", encoding="utf-8") as _f:
                    _json.dump(cf_logs[-200:], _f, ensure_ascii=False, indent=2, default=str)
        except Exception as cf_err:
            console.print(f"[dim][ExecutionAgent] Counterfactual skipped: {cf_err}[/dim]")
            
        return context

class AgentOrchestrator:
    """
    AgentOrchestrator: Điều phối tuần tự tất cả các Agent trong Core Loop.
    """
    def __init__(self):
        self.market_analyst = MarketAnalystAgent()
        self.signal_generator = SignalGeneratorAgent()
        self.risk_manager = RiskManagerAgent()
        self.portfolio_manager = PortfolioManagerAgent()
        self.rl_exit = RLExitAgent()
        self.execution = ExecutionAgent()

    async def run_cycle(
        self,
        raw_candles_dict: Dict[str, List[Dict]],
        mtf_candles_dict: Dict[str, Dict[str, List[Dict]]]
    ) -> Dict[str, Any]:
        """
        Kích hoạt Core Loop chạy qua tất cả các Agent.
        """
        context = {
            "raw_candles": raw_candles_dict,
            "mtf_candles": mtf_candles_dict,
            "timestamp": time.time()
        }
        
        # Thực thi tuần tự chuỗi Agent
        context = self.market_analyst.run(context)
        context = self.signal_generator.run(context)
        context = self.risk_manager.run(context)
        context = self.portfolio_manager.run(context)
        context = self.rl_exit.run(context)
        context = await self.execution.run(context)
        
        return context
