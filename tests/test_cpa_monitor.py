import ast
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


class MonitorTests(unittest.TestCase):
    def test_main_outputs_and_calibration_without_network(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script = root / "scripts" / "cpa_monitor.py"
            script.parent.mkdir()
            source = (SCRIPTS / "cpa_monitor.py").read_text()
            script.write_text(source)
            ns = runpy.run_path(str(script))
            g = ns["main"].__globals__
            coin = {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin",
                    "market_cap_rank": 1, "current_price": 100,
                    "price_change_percentage_7d_in_currency": None,
                    "price_change_percentage_30d_in_currency": None}
            with patch.dict(g, {"universe": lambda: [coin],
                                "tech": lambda c, cache: {"ok": False, "source": "fixture"},
                                "deriv": lambda c: {"deriv": False},
                                "active_events": lambda: ("LOW", [])}):
                with patch("urllib.request.urlopen", side_effect=AssertionError("No network in tests")):
                    ns["main"]()
            data = root / "docs" / "cpa" / "data"
            for filename in ["latest", "monitor_state", "alerts", "tech_cache",
                             "performance_history", "calibration_history", "calibration_report"]:
                json.loads((data / (filename + ".json")).read_text())
            result = json.loads((data / "latest.json").read_text())
            self.assertEqual(result["core"][0]["status"], "UNVERIFIED")
            self.assertEqual(result["core"][0]["confidence"], 45)
            self.assertEqual(result["alerts"], [])
            self.assertEqual(result["regime"]["score"], 41)
            # Ensure direct workflow invocation still calls main().
            guard = ast.parse(source).body[-1]
            self.assertIsInstance(guard, ast.If)
            self.assertEqual(ast.unparse(guard.test), "__name__ == '__main__'")
            self.assertEqual(ast.unparse(guard.body[0]), "main()")
