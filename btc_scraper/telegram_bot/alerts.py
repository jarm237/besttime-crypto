import html
from btc_scraper.core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .api import send_telegram_message

def send_signals_alert(analysis_results: dict[str, dict], mtf_analysis: dict | None = None) -> int | None:

    """
    [LUỒNG CORE] Phân tích tín hiệu và gửi ngay về Telegram (< 1 giây).
    Trả về message_id của tin nhắn vừa gửi để background worker có thể reply AI sau.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return None

    import html

    # Lọc ra các coin có tín hiệu hành động (BUY/SELL)
    active_signals = []
    neutral_signals = []
    missed_valid_signals = []
    
    from btc_scraper.ml_engine.signal_score import extract_signal_fields
    def _is_actionable_alert(signal_text: str) -> bool:
        sig_text = str(signal_text).upper()
        if "NEUTRAL" in sig_text:
            return False
        return any(token in sig_text for token in ("BUY", "SELL", "SHORT", "LONG"))

    for key, ana in analysis_results.items():
        coin, exchange = key.split(":")
        sig_fields = extract_signal_fields(ana)
        sig = ana.get("signal", sig_fields.get("raw", ""))
        
        # Định dạng dòng tin nhắn
        close_val = ana.get('close', 0.0)
        val_format = ",.4f" if close_val < 10 else ",.2f"
        price_str = f"{close_val:{val_format}}"
        
        sig_score = ana.get("signal_score", {}) or {}
        display_label = sig_score.get("display_label")  # e.g. "BUY 80%" / "SELL 75%" / "NEUTRAL"
        display_score = sig_score.get("display_score")  # sức mạnh theo chiều action 0-100
        confidence = sig_score.get("confidence")
        meta_pct = sig_score.get("meta_confidence_pct")  # int 0-100 hoặc None

        # Đồng bộ nhãn hiển thị để tránh mâu thuẫn kiểu "STRONG SELL" nhưng điểm thấp/confidence LOW.
        sig_for_display = str(sig)
        try:
            score_num = float(display_score) if display_score is not None else None
        except Exception:
            score_num = None
        low_conviction = (confidence == "LOW") or (score_num is not None and score_num < 60)
        if low_conviction:
            up = sig_for_display.upper()
            if "STRONG BUY" in up:
                sig_for_display = sig_for_display.replace("STRONG BUY", "WEAK BUY")
            elif "STRONG SELL" in up:
                sig_for_display = sig_for_display.replace("STRONG SELL", "WEAK SELL")

        emoji = "⚪"
        up_sig_display = sig_for_display.upper()
        if "STRONG BUY" in up_sig_display or "LONG" in up_sig_display:
            emoji = "🟢🟢"
        elif "BUY" in up_sig_display:
            emoji = "🟢"
        elif "STRONG SELL" in up_sig_display or "SHORT" in up_sig_display:
            emoji = "🔴🔴"
        elif "SELL" in up_sig_display:
            emoji = "🔴"

        escaped_sig = html.escape(sig_for_display)
        escaped_reason = html.escape(ana.get("reason", ""))

        # Fallback nếu bot đang chạy mà chưa có display_label (dữ liệu cũ)
        if display_label is None:
            score_val = sig_score.get("score")
            action = sig_score.get("action", "NEUTRAL")
            if score_val is not None:
                if action == "BUY":
                    display_label = f"BUY {score_val}%"
                    display_score = score_val
                elif action == "SELL":
                    display_label = f"SELL {100 - score_val}%"
                    display_score = 100 - score_val
                else:
                    display_label = "NEUTRAL"
                    display_score = 0

        if display_label and confidence and display_label != "NEUTRAL":
            score_part = f" <b>[{display_label} {confidence}]</b>"
        elif display_label == "NEUTRAL":
            score_part = f" <b>[→ NEUTRAL]</b>"
        else:
            score_part = ""

        # Meta Confidence badge (chỉ hiển thị khi model đã train)
        if meta_pct is not None:
            if meta_pct >= 70:
                meta_emoji = "🟢"
            elif meta_pct >= 50:
                meta_emoji = "🟡"
            else:
                meta_emoji = "🔴"
            meta_part = f" | {meta_emoji} <b>Meta: {meta_pct}%</b>"
        else:
            meta_part = ""

        kelly_part = ""
        kelly_fraction = sig_score.get("kelly_fraction")
        if kelly_fraction is not None:
            try:
                kelly_part = f" | <b>Kelly: {float(kelly_fraction) * 100:.1f}%</b>"
            except Exception:
                kelly_part = ""

        line = f"{emoji} <b>{coin}</b>: <b>{escaped_sig}</b>{score_part}{meta_part}{kelly_part} giá <code>{price_str}</code> (RSI: {ana['rsi']:.1f})\n<i>{escaped_reason}</i>"
        
        tp_sl = ana.get("tp_sl", {})
        if ("BUY" in sig or "SELL" in sig) and tp_sl:
            entry_val = tp_sl.get("entry", 0.0)
            sl_val = tp_sl.get("sl", 0.0)
            tp1_val = tp_sl.get("tp1", 0.0)
            tp2_val = tp_sl.get("tp2", 0.0)
            rr1_val = tp_sl.get("rr1", 0.0)
            rr2_val = tp_sl.get("rr2", 0.0)
            
            entry_str = f"{entry_val:{val_format}}" if entry_val > 0 else "N/A"
            sl_str = f"{sl_val:{val_format}}" if sl_val > 0 else "N/A"
            tp1_str = f"{tp1_val:{val_format}}" if tp1_val > 0 else "N/A"
            tp2_str = f"{tp2_val:{val_format}}" if tp2_val > 0 else "N/A"
            
            line += (
                f"\n  👉 <b>Entry</b>: <code>{entry_str}</code> | <b>SL</b>: <code>{sl_str}</code>\n"
                f"  👉 <b>TP1</b>: <code>{tp1_str}</code> (R:R {rr1_val}) | <b>TP2</b>: <code>{tp2_str}</code> (R:R {rr2_val})"
            )
            
            if entry_val > 0 and sl_val > 0 and tp1_val > 0:
                tp1_pct = abs(tp1_val - entry_val) / entry_val * 100
                TARGET_USD = 5.0
                FEE_SPOT = 0.20
                FEE_SPOT_BNB = 0.15
                FEE_FUTURES = 0.10
                
                net_spot = tp1_pct - FEE_SPOT
                net_bnb = tp1_pct - FEE_SPOT_BNB
                net_fut = tp1_pct - FEE_FUTURES
                
                def _fmt(net: float) -> str:
                    if net <= 0:
                        return "❌"
                    return f"${TARGET_USD / (net / 100):,.0f}"
                
                line += f"\n  💰 <b>Vốn tối thiểu (lãi ≥$5)</b>: Spot <code>{_fmt(net_spot)}</code> | +BNB <code>{_fmt(net_bnb)}</code> | Fut <code>{_fmt(net_fut)}</code>"
            
        if _is_actionable_alert(sig):
            active_signals.append(line)
        else:
            neutral_signals.append(line)
            
        # Kiểm tra tín hiệu bỏ lỡ còn hiệu lực (Running)
        for ms in ana.get("missed_signals", []):
            if "Running" in ms["status"]:
                ms_fields = extract_signal_fields(ms)
                ms_sig = ms.get("signal", ms_fields.get("raw", ""))
                ms_emoji = "⏳ 🟢" if "BUY" in ms_sig else "⏳ 🔴"
                ms_val_format = ",.4f" if ms["entry"] < 10 else ",.2f"
                ms_entry_str = f"{ms['entry']:{ms_val_format}}"

                try:
                    ms_current_price = float(ms.get("current_price", close_val))
                except (TypeError, ValueError):
                    ms_current_price = None
                ms_current_price_str = f"{ms_current_price:{ms_val_format}}" if ms_current_price is not None and ms_current_price > 0 else "-"
                
                ms_tp_sl = ms["tp_sl"]
                ms_sl_str = f"{ms_tp_sl.get('sl', 0.0):{ms_val_format}}"
                ms_tp1_str = f"{ms_tp_sl.get('tp1', 0.0):{ms_val_format}}"
                ms_tp2_str = f"{ms_tp_sl.get('tp2', 0.0):{ms_val_format}}"
                
                escaped_ms_sig = html.escape(ms_sig)
                ms_line = (
                    f"{ms_emoji} <b>{coin}</b> (Tín hiệu cũ {ms['age_minutes']}p trước): <b>{escaped_ms_sig}</b>\n"
                    f"  Entry cũ: <code>{ms_entry_str}</code> | Giá hiện tại: <code>{ms_current_price_str}</code>\n"
                    f"  SL: <code>{ms_sl_str}</code> | TP1: <code>{ms_tp1_str}</code> (R:R {ms_tp_sl.get('rr1', 0.0)}) | TP2: <code>{ms_tp2_str}</code> (R:R {ms_tp_sl.get('rr2', 0.0)})"
                )
                missed_valid_signals.append(ms_line)
            
    # Gửi từng phần tin nhắn riêng biệt để tránh gộp chung gây rối mắt
    def _send_section(title: str, items: list[str]) -> int | None:
        if not items:
            return None
            
        header = f"🔔 <b>[BÁO CÁO THỊ TRƯỜNG CRYPTO]</b> 🔔\nKhung nến: <b>15m</b>\n{title}"
        chunk_text = header
        first_msg_id = None
        
        for line in items:
            if len(chunk_text) + len(line) + 1 > 4000:
                msg_id = send_telegram_message(chunk_text, parse_mode="HTML")
                if first_msg_id is None:
                    first_msg_id = msg_id
                chunk_text = f"🔔 <b>[BÁO CÁO THỊ TRƯỜNG CRYPTO] (tiếp theo)</b> 🔔\nKhung nến: <b>15m</b>\n{title} (tiếp theo)" + "\n" + line
            else:
                chunk_text += "\n" + line
                
        if chunk_text != header:
            msg_id = send_telegram_message(chunk_text, parse_mode="HTML")
            if first_msg_id is None:
                first_msg_id = msg_id
                
        return first_msg_id

    neutral_msg_id = _send_section("\n📈 <b>Trạng thái thị trường:</b>", neutral_signals)
    missed_msg_id = _send_section("\n⏳ <b>THEO DÕI TÍN HIỆU ĐÃ CÓ TRƯỚC ĐÓ:</b>", missed_valid_signals)
    active_msg_id = _send_section("\n🔥 <b>TÍN HIỆU ĐÁNG CHÚ Ý:</b>", active_signals)
    
    # MTF (1h/4h/1d) signals section (nếu có dữ liệu được truyền vào)
    htf_msg_id = None
    # [Removed] HTF report notification per user request

    
    # Trả về message_id ưu tiên để AI reply vào (ưu tiên Tín hiệu đáng chú ý)
    if active_msg_id is not None:
        return active_msg_id
    if missed_msg_id is not None:
        return missed_msg_id
    # Nếu không có active/missed, ưu tiên trả về HTF nếu có
    if htf_msg_id is not None:
        return htf_msg_id
    return neutral_msg_id


def send_ai_reply(ai_report: str, reply_to_message_id: int | None = None) -> None:
    """
    [LUỒNG AI - BACKGROUND] Gửi nhận định Gemini AI về Telegram.
    - Nếu có reply_to_message_id: gửi dưới dạng reply của tin nhắn signal gốc.
    - Nếu gặp lỗi bất kỳ (429, 503, network): log ra stdout và bỏ qua.
    """
    if not ai_report:
        return
    if ai_report.startswith("[Warning]") or ai_report.startswith("[Loi AI Analyst]") or ai_report.startswith("[Tạm dừng]"):
        print(f"[AI Worker] Bỏ qua gửi Telegram do AI báo lỗi: {ai_report[:80]}...")
        return

    # Giới hạn 4000 ký tự mỗi tin để không vượt giới hạn Telegram
    ai_header = "🤖 NHAN DINH GEMINI AI:\n" + "-" * 30 + "\n"
    first_chunk = True
    remaining = ai_report

    while remaining:
        chunk = remaining[:3900]
        remaining = remaining[3900:]

        # Chỉ reply vào tin nhắn gốc cho phần đầu tiên; các phần tiếp theo gửi thường
        rid = reply_to_message_id if first_chunk else None
        send_telegram_message(ai_header + chunk, parse_mode=None, reply_to_message_id=rid)

        ai_header = "🤖 NHAN DINH GEMINI AI (tiep theo):\n" + "-" * 30 + "\n"
        first_chunk = False


def send_position_recommendations(recommendations: list[dict]) -> None:
    """
    Gửi thông báo cập nhật về các vị thế đang mở qua Telegram.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not recommendations:
        return

    import html
    message_lines = ["🛡️ <b>[CẬP NHẬT VỊ THẾ ĐANG MỞ]</b> 🛡️\n"]

    for rec in recommendations:
        coin = rec["coin"]
        direction = rec["direction"]
        pnl = rec["pnl_pct"]
        urgency = rec["urgency"]
        action = rec["action"] if "action" in rec else rec["recommendation"]
        current_price = rec.get("current_price", 0.0)
        entry_price = rec.get("entry_price", 0.0)
        
        # Biểu tượng mức độ khẩn cấp
        icon = "🟢"
        if urgency == "HIGH":
            icon = "🚨"
        elif urgency == "MEDIUM":
            icon = "⚠️"
        
        # PnL color
        pnl_text = f"lãi +{pnl:.2f}%" if pnl > 0 else f"lỗ {pnl:.2f}%"
        
        val_format = ",.4f" if current_price > 0 and current_price < 10 else ",.2f"
        current_price_str = f"{current_price:{val_format}}" if current_price > 0 else "N/A"
        
        entry_val_format = ",.4f" if entry_price > 0 and entry_price < 10 else ",.2f"
        entry_price_str = f"{entry_price:{entry_val_format}}" if entry_price > 0 else "N/A"
        
        escaped_action = html.escape(action)
        escaped_reason = html.escape(rec["recommendation_reason"])

        meta_part = ""
        live_meta = rec.get("live_meta_confidence")
        if live_meta is not None:
            live_meta_pct = int(round(live_meta * 100))
            if live_meta_pct >= 70:
                meta_emoji = "🟢"
            elif live_meta_pct >= 50:
                meta_emoji = "🟡"
            else:
                meta_emoji = "🔴"
            meta_part = f" | {meta_emoji} <b>XS thắng: {live_meta_pct}%</b>"
        
        dca_opp = rec.get("dca_opportunity")
        if dca_opp:
            icon = "➕"
            dca_size = dca_opp["suggested_dca_size"]
            new_avg_entry = dca_opp["new_avg_entry"]
            sim_meta = int(round(dca_opp["sim_meta_prob"] * 100))
            dca_conf_label = dca_opp.get("confidence_label", "MEDIUM")
            rl_at_eval = dca_opp.get("rl_action_at_eval")

            new_entry_format = ",.4f" if new_avg_entry > 0 and new_avg_entry < 10 else ",.2f"
            new_avg_entry_str = f"{new_avg_entry:{new_entry_format}}"

            # Map rl_action number to readable label
            RL_LABEL_MAP = {0: "HOLD", 2: "TRAILING-BE", 5: "TRAILING-SL", None: "N/A"}
            rl_label_str = RL_LABEL_MAP.get(rl_at_eval, str(rl_at_eval))

            # Confidence icon
            conf_icon = "🔥" if dca_conf_label == "HIGH" else "🟡"

            line = (
                f"{icon} <b>[KHUYẾN NGHỊ DCA] {coin} ({direction})</b>: {pnl_text}\n"
                f"  👉 <b>Khuyên dùng DCA thêm ${dca_size:.2f} USDT tại {current_price_str}</b>\n"
                f"  💰 Entry cũ: <code>{entry_price_str}</code> | Entry mới: <code>{new_avg_entry_str}</code>\n"
                f"  🤖 <b>XS thắng DCA: {sim_meta}%</b> (Reversal Prob)\n"
                f"  {conf_icon} Confidence: <b>{dca_conf_label}</b> | RL lúc đánh giá: {rl_label_str}\n"
            )

        else:
            line = (
                f"{icon} <b>{coin}</b> ({direction}){meta_part}: {pnl_text}\n"
                f"  👉 <b>{escaped_action}</b>\n"
                f"  💰 Entry: <code>{entry_price_str}</code> | Hiện tại: <code>{current_price_str}</code>\n"
                f"  <i>{escaped_reason}</i>\n"
            )
        message_lines.append(line)

    message = "\n".join(message_lines)
    send_telegram_message(message, parse_mode="HTML")


def send_causal_analysis_alert(decision_with_reasoning: dict) -> int | None:
    """
    [PHASE 4] Gửi phân tích nhân quả chi tiết về Telegram.
    
    Hiển thị:
    - Causal pathway từ macro drivers đến BTC/ETH
    - Root causes chính tác động
    - Confidence breakdown
    
    Args:
        decision_with_reasoning: Output từ causal_reasoning.explain_decision()
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not decision_with_reasoning:
        return None

    causal_reasoning = decision_with_reasoning.get("causal_reasoning", {})
    if not causal_reasoning:
        return None

    target = causal_reasoning.get("target", "BTC")
    explanation = causal_reasoning.get("explanation", "")
    root_causes = causal_reasoning.get("root_causes", [])
    primary_path = causal_reasoning.get("primary_path", {})

    # Build message
    lines = [
        "🧬 <b>[PHÂN TÍCH NHÂN QUẢ - CAUSAL ANALYSIS]</b> 🧬",
        f"Mục tiêu: <b>{target}</b>",
        "",
        f"💡 <i>{explanation}</i>",
        "",
    ]

    # Root causes
    if root_causes:
        lines.append("<b>🔗 Nguyên nhân gốc (Root Causes):</b>")
        for cause, conf in root_causes[:3]:
            conf_pct = int(round(conf * 100))
            lines.append(f"  • {cause} ({conf_pct}% confidence)")
        lines.append("")

    # Primary pathway
    if primary_path:
        path = primary_path.get("path", [])
        confidence = primary_path.get("confidence", 0)
        effect = primary_path.get("effect_direction", "neutral")
        num_hops = primary_path.get("num_hops", 0)

        path_str = " → ".join(path) if path else "N/A"
        effect_emoji = "📈" if effect == "positive" else "📉"
        conf_pct = int(round(confidence * 100))

        lines.append(f"<b>{effect_emoji} Đường dẫn chính:</b>")
        lines.append(f"  <code>{path_str}</code>")
        lines.append(f"  Confidence: {conf_pct}% | Hops: {num_hops}")
        lines.append("")

    message = "\n".join(lines)
    return send_telegram_message(message, parse_mode="HTML")


def send_context_adjustment_alert(context_report: dict, original_decision: dict) -> int | None:
    """
    [PHASE 3] Gửi thông báo điều chỉnh Context lên Telegram.
    
    Hiển thị:
    - Original score vs Adjusted score
    - Context adjustments layer-by-layer
    - Risk level warning
    
    Args:
        context_report: Output từ context_engine.generate_context_report()
        original_decision: Output từ decision_engine.decide()
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return None

    if not context_report:
        return None

    original_score = context_report.get("original_score", 0.5)
    adjusted_score = context_report.get("adjusted_score", 0.5)
    risk_level = context_report.get("risk_level", "LOW")
    adjustments = context_report.get("adjustments", [])
    stop_processing = context_report.get("stop_processing", False)

    # Risk level emoji
    risk_emoji = {
        "LOW": "🟢",
        "MEDIUM": "🟡",
        "HIGH": "🔴",
        "CRITICAL": "🔴🔴",
    }.get(risk_level, "⚪")

    # Build message
    lines = [
        f"⚙️ <b>[ĐIỀU CHỈNH CONTEXT - CONTEXT ADJUSTMENT]</b> ⚙️",
        "",
        f"Điểm gốc: <code>{original_score:.2f}</code> → Điểm điều chỉnh: <code>{adjusted_score:.2f}</code>",
        f"Mức độ rủi ro: {risk_emoji} <b>{risk_level}</b>",
        "",
    ]

    # Adjustments by layer
    if adjustments:
        lines.append("<b>🎯 Điều chỉnh từng layer:</b>")
        
        by_layer = {}
        for adj in adjustments:
            layer = adj.get("layer", "unknown")
            if layer not in by_layer:
                by_layer[layer] = []
            by_layer[layer].append(adj)

        for layer, layer_adjustments in by_layer.items():
            total_impact = sum(a.get("impact", 0) for a in layer_adjustments)
            impact_emoji = "📈" if total_impact >= 0 else "📉"
            lines.append(f"  {impact_emoji} <b>{layer}</b>: {total_impact:+.3f}")

            for adj in layer_adjustments[:2]:  # Show top 2 per layer
                reason = adj.get("reason", "")
                impact = adj.get("impact", 0)
                lines.append(f"    • {reason} ({impact:+.3f})")

        lines.append("")

    # Stop processing warning
    if stop_processing:
        lines.append("⚠️ <b>[CẢNH BÁO] Context engine DỪNG xử lý - Điều kiện nguy hiểm phát hiện!</b>")
        lines.append("")

    message = "\n".join(lines)
    return send_telegram_message(message, parse_mode="HTML")


def send_shadow_mode_report(
    original_decision: dict,
    context_adjusted_decision: dict,
    context_report: dict,
) -> int | None:
    """
    [VERIFICATION PLAN] Gửi báo cáo so sánh Original vs Context-Adjusted qua Telegram.
    
    Dùng trong Shadow Mode để theo dõi PnL nếu trade theo cách cũ vs cách mới.
    
    Args:
        original_decision: Original decision (Meta Model only)
        context_adjusted_decision: Decision với Context adjustment
        context_report: Context report
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return None

    original_action = original_decision.get("action", "NEUTRAL")
    adjusted_action = context_adjusted_decision.get("action", "NEUTRAL")
    
    original_posterior = original_decision.get("posterior_probability", 0.5)
    adjusted_posterior = context_adjusted_decision.get("adjusted_posterior", 0.5)

    # Build message
    lines = [
        "📊 <b>[SHADOW MODE - SO SÁNH KQUA]</b> 📊",
        "",
        "<b>Quyết định cũ (Meta Model only):</b>",
        f"  Action: <b>{original_action}</b> | Posterior: {original_posterior:.3f}",
        "",
        "<b>Quyết định mới (với Context Adjustment):</b>",
        f"  Action: <b>{adjusted_action}</b> | Posterior: {adjusted_posterior:.3f}",
        "",
    ]

    # Decision change
    if original_action != adjusted_action:
        lines.append(f"⚠️ <b>THAY ĐỔI QUYẾT ĐỊNH:</b> {original_action} → {adjusted_action}")
        lines.append("")

    # Context impact
    context_adjustment = context_adjusted_decision.get("context_adjustment", 0)
    lines.append(f"Impact của Context: {context_adjustment:+.3f}")

    message = "\n".join(lines)
    return send_telegram_message(message, parse_mode="HTML")


