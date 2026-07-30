from btc_scraper.ml_engine.multi_agent import SignalGeneratorAgent


def test_signal_generator_attaches_reference_only_after_decision(monkeypatch):
    hostile_reference = {
        "mode": "reference_only",
        "affects_signal": False,
        "decision_eligible": False,
        "status": "available",
        "values": {"risk_on_score": -1.0, "funding_pressure": 1.0},
        "summary": "risk_on=-1.000 | funding=1.000",
    }
    captured = {}

    monkeypatch.setattr(
        "btc_scraper.collectors.alternative_reference.load_alternative_reference",
        lambda: hostile_reference,
    )

    def fake_score(analysis, *, meta_prediction=None):
        assert "alternative_data_reference" not in analysis
        return {
            "action": "BUY",
            "meta_confidence": 0.8,
            "kelly_fraction": 0.1,
        }

    def fake_causal(ana, analysis_info, alpha):
        assert "alternative_data_reference" not in ana
        assert "alternative_data_reference" not in analysis_info
        captured["called"] = True
        return {}

    monkeypatch.setattr("btc_scraper.ml_engine.signal_score.evaluate_signal_score", fake_score)
    monkeypatch.setattr(
        "btc_scraper.ml_engine.causal_context_bridge.enhance_signal_with_causal_context",
        fake_causal,
    )

    context = {
        "analysis": {
            "BTC:Binance": {
                "signal": "BUY",
                "close": 65000.0,
                "atr": 500.0,
            }
        }
    }
    result = SignalGeneratorAgent().run(context)

    assert captured["called"] is True
    assert result["signals_info"][0]["action"] == "BUY"
    assert "alternative_data_reference" not in result["signals_info"][0]
    assert result["analysis"]["BTC:Binance"]["alternative_data_reference"] == hostile_reference
    assert result["alternative_data_reference"] == hostile_reference


def test_reference_load_failure_does_not_block_signal_generation(monkeypatch):
    monkeypatch.setattr(
        "btc_scraper.collectors.alternative_reference.load_alternative_reference",
        lambda: (_ for _ in ()).throw(RuntimeError("broken snapshot")),
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.signal_score.evaluate_signal_score",
        lambda analysis, **kwargs: {
            "action": "SELL",
            "meta_confidence": 0.7,
            "kelly_fraction": 0.05,
        },
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.causal_context_bridge.enhance_signal_with_causal_context",
        lambda **kwargs: {},
    )

    result = SignalGeneratorAgent().run({
        "analysis": {
            "ETH:Binance": {
                "signal": "SELL",
                "close": 3500.0,
                "atr": 50.0,
            }
        }
    })

    assert result["signals_info"][0]["action"] == "SELL"
    reference = result["analysis"]["ETH:Binance"]["alternative_data_reference"]
    assert reference["decision_eligible"] is False
    assert reference["status"] == "stale"
    assert reference["load_error"] == "broken snapshot"
