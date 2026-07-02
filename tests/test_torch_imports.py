import importlib
import unittest


class TorchImportCompatibilityTest(unittest.TestCase):
    def test_core_modules_import_without_torch(self):
        modules = [
            "btc_scraper.ml_engine.timegan",
            "btc_scraper.ml_engine.timegan_model",
            "btc_scraper.ml_engine.timegan_generate",
            "btc_scraper.ml_engine.timegan_trainer",
            "btc_scraper.trading.position_tracker",
        ]
        for module_name in modules:
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                self.assertIsNotNone(module)


if __name__ == "__main__":
    unittest.main()
