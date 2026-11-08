"""
Multi-Agent AI Platform — Định nghĩa các Agent chuyên biệt và Orchestrator điều phối.
"""

import os
import time
import copy
import uuid
from typing import Dict, Any, Iterable, List
from rich.console import Console

from btc_scraper.analysis import analyze_market
from btc_scraper.core.config import get_analysis_universe
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
    def __init__(self, analysis_symbols: Iterable[str] | None = None):
        super().__init__("MarketAnalyst")
        self.analysis_symbols = tuple(
            analysis_symbols if analysis_symbols is not None else get_analysis_universe()
        )

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        raw_candles = context["raw_candles"]
        mtf_candles = context.get("mtf_candles", {})

        analysis_results = {}
        mtf_analysis_results = {}
        for coin in self.analysis_symbols:
            # 1. Phân tích nến 15m
            candles_15m = raw_candles.get(coin, [])
            if not candles_15m or "error" in candles_15m[0]:
                continue
            analysis_candles_15m = candles_15m[-210:]
            ana = analyze_market(analysis_candles_15m, coin)
            ana["close"] = analysis_candles_15m[-1]["close"]
            if coin in ("BTC", "ETH", "BNB"):
                from btc_scraper.core.candle_store import candle_store
                ana["_shadow_candles_15m"] = candle_store.get(coin, "15m")[-500:]
            analysis_results[f"{coin}:Binance"] = ana
            from btc_scraper.core.milestones import milestone_tracker
            milestone_tracker.record("first_analysis_ready")

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

        from btc_scraper.core.milestones import milestone_tracker
        milestone_tracker.record("all_analysis_ready")
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
        cycle_id = str(
            context.setdefault("cycle_id", f"cycle-{uuid.uuid4().hex}")
        )
        from btc_scraper.collectors.alternative_reference import (
            build_alternative_reference,
            load_alternative_reference,
        )
        from btc_scraper.ml_engine.signal_score import evaluate_signal_score
        from btc_scraper.ml_engine.causal_context_bridge import enhance_signal_with_causal_context
        from btc_scraper.ml_engine.inference_coordinator import get_inference_coordinator

        # Load once per cycle. This object is attached only after every decision
        # operation has completed and is never copied into signals_info.
        try:
            alternative_reference = load_alternative_reference()
        except Exception as exc:
            alternative_reference = build_alternative_reference({})
            alternative_reference["load_error"] = str(exc)
        context["alternative_data_reference"] = copy.deepcopy(alternative_reference)

        signals_info = []
        from btc_scraper.core.config import get_execution_universe
        from btc_scraper.core.milestones import milestone_tracker
        inference_scope = os.getenv("PAPER_INFERENCE_SCOPE", "execution").strip().lower()
        execution_coins = set(get_execution_universe()) if inference_scope == "execution" else None

        quality_status = alternative_reference.get("status", "unavailable")
        if quality_status == "available":
            prediction_quality = "COMPLETE"
        elif quality_status == "partial":
            prediction_quality = "PARTIAL"
        elif quality_status == "stale":
            prediction_quality = "STALE"
        else:
            prediction_quality = "NEUTRAL_DEFAULTS"

        for key, ana in list(analysis.items()):
            coin = key.split(":")[0]
            ana.setdefault("coin", coin)
            ana.setdefault("symbol", f"{coin}USDT")
            ana.setdefault("timeframe", "15m")
            ana["cycle_id"] = cycle_id
            ana["prediction_input_quality"] = prediction_quality

            if execution_coins is not None and coin not in execution_coins:
                ana["execution_eligible"] = False
                ana["skip_reason"] = "ANALYSIS_ONLY_NOT_IN_EXECUTION_UNIVERSE"
                sig_score = {
                    "action": ana.get("action", "HOLD"),
                    "score": 50,
                    "strength": 0,
                    "meta_confidence": 0.5,
                    "kelly_fraction": 0.0,
                    "execution_eligible": False,
                    "skip_reason": "ANALYSIS_ONLY_NOT_IN_EXECUTION_UNIVERSE",
                }
                ana["signal_score"] = sig_score
                ana["alternative_data_reference"] = copy.deepcopy(alternative_reference)
                signals_info.append({
                    "coin": coin,
                    "action": sig_score["action"],
                    "meta_confidence": 0.5,
                    "kelly_fraction": 0.0,
                    "close": ana.get("close", 0.0),
                    "atr": ana.get("atr", 0.0),
                    "signal": ana.get("signal", ""),
                    "execution_eligible": False,
                    "skip_reason": "ANALYSIS_ONLY_NOT_IN_EXECUTION_UNIVERSE",
                })
                continue

            meta_prediction = None
            terminal_error: Exception | None = None
            try:
                meta_prediction = get_inference_coordinator().predict_once(
                    ana,
                    symbol=coin,
                    timeframe=str(ana["timeframe"]),
                    decision_context="entry",
                    caller_context="agent_orchestrator",
                )
                milestone_tracker.record("first_prediction_ready")
            except Exception as exc:
                from btc_scraper.ml_engine.operational_health import record_degradation
                record_degradation("ml_inference", "ml_inference_failure_total", exc)
                # A cycle without its governed Meta prediction is incomplete.
                # Do not convert it into a technical-only alert followed by
                # ``missing_final_decision``; let the runtime pause/fail-closed
                # policy classify the original failure.
                raise
            try:
                sig_score = evaluate_signal_score(
                    ana,
                    meta_prediction=meta_prediction.to_dict() if meta_prediction else None,
                )
            except Exception as exc:
                terminal_error = exc
                meta_lineage = (
                    meta_prediction.to_dict() if meta_prediction is not None else {}
                )
                sig_score = {
                    **meta_lineage,
                    "action": "NEUTRAL",
                    "score": 50,
                    "strength": 0,
                    "risk_status": "UNAVAILABLE",
                    "risk_blocked": True,
                    "meta_error": type(exc).__name__,
                }
            ana["signal_score"] = sig_score
            for field in (
                "signal_id", "prediction_id", "inference_contract_version",
                "model_family", "artifact_version", "artifact_hash",
                "feature_schema_hash", "prediction",
                "artifact_metadata_consistent", "model_version", "artifact_sha256",
                "model_artifact_sha256", "feature_schema_version", "deployment_id",
                "paper_run_id", "cycle_id", "decision_context", "caller_context",
                "feature_hash",
            ):
                if sig_score.get(field) is not None:
                    ana[field] = sig_score[field]

            # Phase C: Tích hợp Causal Context (alpha=0.0 = safe mode, chỉ rules)
            causal_error: Exception | None = terminal_error
            try:
                causal_enhanced = (
                    enhance_signal_with_causal_context(
                        ana=ana,
                        analysis_info={**ana, **sig_score},
                        alpha=float(os.environ.get("CAUSAL_ALPHA", "0.0")),
                    )
                    if terminal_error is None else {}
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
            except Exception as exc:
                causal_error = exc

            # Every eligible prediction must end in exactly one terminal
            # decision. A context failure is evidence, never a silent gap.
            if sig_score.get("prediction_id") and not ana.get("causal_decision"):
                from btc_scraper.core.paths import (
                    runtime_evidence_eligible,
                    runtime_paper_run_id,
                )
                from btc_scraper.ml_engine.runtime_evidence_store import (
                    get_runtime_evidence_store,
                )

                evidence_store = get_runtime_evidence_store()
                existing = evidence_store.get_final_decision_for_prediction(
                    str(sig_score["prediction_id"])
                )
                if existing is not None:
                    ana["causal_decision"] = existing
                else:
                    terminal_error = {
                        "action": "ERROR",
                        "terminal_status": "ERROR",
                        "eligible": False,
                        "superseded": False,
                        "reason": "terminal_decision_unavailable",
                        "error_type": (
                            type(causal_error).__name__
                            if causal_error is not None else "EmptyDecision"
                        ),
                        "decision_id": f"fd-error-{uuid.uuid4().hex}",
                        "prediction_id": sig_score.get("prediction_id"),
                        "signal_id": sig_score.get("signal_id"),
                        "inference_contract_version": sig_score.get(
                            "inference_contract_version"
                        ),
                        "model_family": sig_score.get("model_family"),
                        "artifact_version": sig_score.get("artifact_version"),
                        "artifact_hash": sig_score.get("artifact_hash")
                        or sig_score.get("artifact_sha256"),
                        "feature_schema_hash": sig_score.get(
                            "feature_schema_hash"
                        ),
                        "prediction": sig_score.get("prediction"),
                        "artifact_metadata_consistent": sig_score.get(
                            "artifact_metadata_consistent"
                        ),
                        "cycle_id": cycle_id,
                        "deployment_id": sig_score.get("deployment_id"),
                        "paper_run_id": (
                            sig_score.get("paper_run_id")
                            or runtime_paper_run_id()
                        ),
                        "model_version": sig_score.get("model_version"),
                        "artifact_sha256": sig_score.get("artifact_sha256"),
                        "model_artifact_sha256": sig_score.get("artifact_sha256"),
                        "feature_schema_version": sig_score.get(
                            "feature_schema_version"
                        ),
                        "decision_context": sig_score.get("decision_context"),
                        "caller_context": sig_score.get("caller_context"),
                        "risk_status": str(
                            sig_score.get("risk_status") or "UNAVAILABLE"
                        ).upper(),
                        "risk_blocked": True,
                        "evidence_eligible": runtime_evidence_eligible(),
                    }
                    evidence_store.append_final_decision(terminal_error)
                    ana["causal_decision"] = terminal_error

            # Display/audit context only. Keep this assignment after scoring and
            # causal evaluation so Alternative Data cannot affect real signals.
            ana["alternative_data_reference"] = copy.deepcopy(alternative_reference)

            try:
                from btc_scraper.ml_engine.h14_observer import (
                    observe_h14_prospective_analysis,
                )

                observe_h14_prospective_analysis(ana)
            except Exception as exc:
                from btc_scraper.ml_engine.operational_health import record_degradation

                record_degradation("h14_observer", "h14_observer_failure_total", exc)
            
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
            
        from btc_scraper.core.milestones import milestone_tracker
        milestone_tracker.record("all_predictions_ready")
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
        if risk_metrics.get("blocked", True):
            failure_reason = risk_metrics.get("failure_reason") or f"drawdown={risk_metrics.get('drawdown_pct')}%"
            console.print(f"[bold red][RiskManager] BLOCK_ENTRY: {failure_reason}[/bold red]")
            for s in context["signals_info"]:
                s["action"] = "NEUTRAL"
                s["risk_status"] = risk_metrics.get("status", "UNAVAILABLE")
                s["risk_failure_reason"] = failure_reason
                
        # Áp dụng risk multiplier nếu gặp chuỗi thua
        risk_mult = risk_metrics.get("risk_multiplier", 0.0)
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
    Lazy-loads PPO model only when open positions are present and exit evaluation is required.
    """
    def __init__(self):
        super().__init__("RLExit")
        self.model = None

    def _load_rl_model(self):
        if self.model is None:
            try:
                from btc_scraper.trading.position_tracker import get_ppo_model
                self.model = get_ppo_model()
            except Exception as e:
                console.print(f"[dim red]  [RLExitAgent] Không thể load model RL exit: {e}[/dim red]")
        return self.model

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        # Tác nhân RL chỉ cần thiết khi có vị thế đang mở
        open_positions = context.get("open_positions")
        if open_positions is None:
            try:
                from btc_scraper.trading.position_tracker import get_open_positions
                open_positions = get_open_positions()
            except Exception:
                open_positions = []

        if not open_positions:
            context["rl_model_loaded"] = False
            return context

        model = self._load_rl_model()
        context["rl_model_loaded"] = model is not None
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
            from btc_scraper.core.milestones import milestone_tracker
            await auto_trader.evaluate_and_trade(analysis, mtf_analysis=mtf_analysis)
            milestone_tracker.record("first_final_decision_ready")
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
    def __init__(self, analysis_symbols: Iterable[str] | None = None):
        self.analysis_symbols = tuple(
            analysis_symbols if analysis_symbols is not None else get_analysis_universe()
        )
        self.market_analyst = MarketAnalystAgent(self.analysis_symbols)
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
        open_positions = None
        try:
            from btc_scraper.trading.position_tracker import get_open_positions
            open_positions = get_open_positions()
        except Exception:
            open_positions = []

        context = {
            "raw_candles": raw_candles_dict,
            "mtf_candles": mtf_candles_dict,
            "open_positions": open_positions,
            "timestamp": time.time(),
            "cycle_id": f"cycle-{uuid.uuid4().hex}",
        }
        
        # Thực thi tuần tự chuỗi Agent
        context = self.market_analyst.run(context)
        context = self.signal_generator.run(context)
        context = self.risk_manager.run(context)
        context = self.portfolio_manager.run(context)
        context = self.rl_exit.run(context)
        context = await self.execution.run(context)
        
        return context
