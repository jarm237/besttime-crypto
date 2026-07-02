import logging

from btc_scraper.ml_engine.context_engine import ContextEngine, ExpressionEvaluator


def test_expression_evaluator_handles_dotted_keys_and_constants_without_syntax_errors(caplog):
    context = {
        "MacroEvent": {
            "FOMC": {
                "HoursToEvent": 2,
                "Importance": "HIGH",
            }
        },
        "FedRate": {
            "Change": 0.25,
            "ChartPattern": "ACCELERATING",
            "Direction": "PAUSE",
        },
        "RealYield": 2.2,
        "RealYield_Z": 2.4,
        "DXY": 100.0,
        "DXY_52w_high": 99.0,
        "DXY_Trend": "UP",
        "FearGreed": 19.0,
        "Trend": "DOWN",
        "Sentiment_Trend": "UP",
        "Price_Trend": "DOWN",
        "VolatilityClustering": True,
        "Horizon": "SHORT",
        "BTC_Equity_Correlation": 0.82,
    }

    evaluator = ExpressionEvaluator(context)

    with caplog.at_level(logging.WARNING):
        assert evaluator.evaluate("MacroEvent.FOMC.HoursToEvent < 4 AND MacroEvent.FOMC.Importance == HIGH") is True
        assert evaluator.evaluate("FedRate.Change > 0 AND FedRate.ChartPattern == ACCELERATING") is True
        assert evaluator.evaluate("RealYield > 1.5 AND RealYield_Z > 2") is True
        assert evaluator.evaluate("DXY > DXY_52w_high AND DXY_Trend == UP") is True
        assert evaluator.evaluate("FedRate.Direction == PAUSE") is True
        assert evaluator.evaluate("FearGreed < 25 AND Trend == DOWN") is True
        assert evaluator.evaluate("Sentiment_Trend == UP AND Price_Trend == DOWN") is True
        assert evaluator.evaluate("VolatilityClustering == TRUE AND Horizon == SHORT") is True
        assert evaluator.evaluate("BTC_Equity_Correlation > 0.7") is True

    assert "Failed to evaluate expression" not in caplog.text


def test_expression_evaluator_missing_variables_return_false_not_exception(caplog):
    evaluator = ExpressionEvaluator({"DXY": 101.0})

    with caplog.at_level(logging.WARNING):
        assert evaluator.evaluate("Portfolio.ExposurePercentage > 60") is False
        assert evaluator.evaluate("DrawdownPct > 15") is False

    assert "Failed to evaluate expression" not in caplog.text


def test_expression_evaluator_numeric_string_compares_as_number(caplog):
    evaluator = ExpressionEvaluator({"BTC_RSI": "72", "BTC_Trend": "UP"})

    with caplog.at_level(logging.WARNING):
        assert evaluator.evaluate("BTC_RSI > 70 AND BTC_Trend == UP") is True

    assert "Failed to evaluate expression" not in caplog.text


def test_expression_evaluator_numeric_like_string_formats(caplog):
    evaluator = ExpressionEvaluator({"BTC_RSI": "70.5%", "BTC_Trend": "UP"})

    with caplog.at_level(logging.WARNING):
        assert evaluator.evaluate("BTC_RSI > 70 AND BTC_Trend == UP") is True

    evaluator_with_comma = ExpressionEvaluator({"BTC_RSI": "1,234.5", "BTC_Trend": "UP"})
    with caplog.at_level(logging.WARNING):
        assert evaluator_with_comma.evaluate("BTC_RSI > 70 AND BTC_Trend == UP") is True

    assert "Failed to evaluate expression" not in caplog.text


def test_expression_evaluator_non_numeric_string_in_numeric_compare_returns_false(caplog):
    evaluator = ExpressionEvaluator({"BTC_RSI": "N/A", "BTC_Trend": "UP"})

    with caplog.at_level(logging.WARNING):
        assert evaluator.evaluate("BTC_RSI > 70 AND BTC_Trend == UP") is False

    assert "Failed to evaluate expression" not in caplog.text


def test_expression_evaluator_missing_numeric_token_does_not_become_string_constant(caplog):
    evaluator = ExpressionEvaluator({})

    with caplog.at_level(logging.WARNING):
        assert evaluator.evaluate("BTC_RSI > 70 AND BTC_Trend == UP") is False

    assert "Failed to evaluate expression" not in caplog.text


def test_context_engine_market_layer_reads_crypto_rules():
    engine = ContextEngine("data/context_rules.json")
    market_rules = engine._get_rules_by_layer("market")

    assert isinstance(market_rules, list)
    assert len(market_rules) > 0
