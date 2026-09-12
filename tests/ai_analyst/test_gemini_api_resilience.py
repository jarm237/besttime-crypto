"""Tests for call_gemini 503 retry, 429 quota exhaustion, and key masking resilience."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
from btc_scraper.ai_analyst.api import call_gemini, _key_manager


class TestGeminiApiResilience(unittest.TestCase):
    def setUp(self):
        _key_manager._exhausted.clear()
        _key_manager._paused_until = None

    @patch("btc_scraper.ai_analyst.api.genai.Client")
    @patch("time.sleep", return_value=None)
    def test_call_gemini_503_retries_and_returns_degraded(self, mock_sleep, mock_client_cls):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("503 Service Unavailable")
        mock_client_cls.return_value = mock_client

        res = call_gemini("test prompt")
        self.assertIn("[Degraded]", res)
        self.assertIn("503 UNAVAILABLE", res)
        # Verify key was NOT marked exhausted on 503
        self.assertTrue(_key_manager.available)

    @patch("btc_scraper.ai_analyst.api.genai.Client")
    @patch("time.sleep", return_value=None)
    def test_call_gemini_429_exhausts_key(self, mock_sleep, mock_client_cls):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED")
        mock_client_cls.return_value = mock_client

        res = call_gemini("test prompt")
        self.assertTrue("Tạm dừng" in res or "Degraded" in res or "quota" in res)

    @patch("btc_scraper.ai_analyst.api.genai.Client")
    def test_call_gemini_masks_key_in_logs(self, mock_client_cls):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "AI response text"
        mock_client.models.generate_content.return_value = mock_response
        mock_client_cls.return_value = mock_client

        with patch("builtins.print") as mock_print:
            res = call_gemini("test prompt")
            self.assertEqual(res, "AI response text")
            for call_args in mock_print.call_args_list:
                printed_text = str(call_args)
                # Ensure no raw API key string is printed in plaintext
                for key in _key_manager._keys:
                    if len(key) > 6:
                        self.assertNotIn(key, printed_text)


if __name__ == "__main__":
    unittest.main()
