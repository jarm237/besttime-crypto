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
            ana = analyze_market(candles_15m)
            ana["close"] = candles_15m[-1]["close"]
            analysis_results[f"{coin}:Binance"] = ana

            # 2. Phân tích đa khung thời gian (MTF)
            coin_mtf = mtf_candles.get(coin, {})
            mtf_ana_dict = {}
            for tf in ["1h", "4h", "1d"]:
                tf_candles = coin_mtf.get(tf, [])
                if tf_candles and "error" not in tf_candles[0]:
                    tf_ana = analyze_market(tf_candles)
                    tf_ana["close"] = tf_candles[-1]["close"]
                    mtf_ana_dict[tf] = tf_ana
            
            mtf_analysis_results[coin] = mtf_ana_dict
            
            # Gắn HTF Trend
            from main import _summarize_htf_trend, _format_htf_details
            htf_trend = _summarize_htf_trend(mtf_ana_dict)
            htf_details = _format_htf_details(mtf_ana_dict)
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
        
        signals_info = []
        for key, ana in list(analysis.items()):
            coin = key.split(":")[0]
            # Chấm điểm và dự báo xác suất thắng
            sig_score = evaluate_signal_score(ana)
            ana["signal_score"] = sig_score
            
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
            
        # 2. Ghi nhận dự báo vào Shadow Predictions Log (Shadow Mode)
        try:
            from scripts.shadow_log import log_signal_prediction
            for key, ana in analysis.items():
                sig_score = ana.get("signal_score") or {}
                meta_prob = sig_score.get("meta_confidence")
                sig = ana.get("signal", "")
                if meta_prob is not None and ("BUY" in sig or "SELL" in sig):
                    coin = key.split(":")[0]
                    log_signal_prediction(
                        symbol=f"{coin}USDT",
                        signal=sig,
                        meta_prob=meta_prob,
                        signal_score=sig_score.get("score", 50),
                        regime=ana.get("regime") or (sig_score.get("regime") or ""),
                        htf_trend=ana.get("htf_trend", ""),
                    )
        except Exception as e:
            console.print(f"[dim red][ExecutionAgent] Lỗi ghi shadow log: {e}[/dim red]")
            
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
