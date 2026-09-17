import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cpa_calibration import advance

REGIME = {"name": "NEUTRAL", "score": 55}


def row(score=4, status="CONFIRMED", price=100):
    return {"id": "bitcoin", "symbol": "BTC", "price": price,
            "confirmation_score": score, "status": status, "action_score": 72,
            "event_risk": "LOW", "event_score": 0, "data_source": "fixture"}


class CalibrationTests(unittest.TestCase):
    def test_entry_frozen_and_no_mutation_or_duplicate(self):
        rows = [row(3, "NEAR ENTRY")]
        original = copy.deepcopy(rows)
        state, report = advance({}, rows, REGIME, "2026-09-17T00:00:00Z")
        advance(state, [row(5)], {"name": "RISK-ON", "score": 85}, "2026-09-17T01:00:00Z")
        self.assertEqual(rows, original)
        self.assertEqual(len(state["observations"]), 1)
        self.assertEqual(state["observations"][0]["confirmation_score"], 3)
        self.assertEqual(state["observations"][0]["regime"], "NEUTRAL")
        self.assertFalse(report["automatic_reweighting"])

    def test_horizons_missing_and_actual_elapsed_time(self):
        state, _ = advance({}, [row()], REGIME, "2026-09-17T00:00:00Z")
        advance(state, [row(price=110)], REGIME, "2026-09-17T23:59:00Z")
        self.assertEqual(state["observations"][0]["outcomes"], {})
        _, report = advance(state, [row(price=110)], REGIME, "2026-09-18T00:30:00Z")
        outcome = state["observations"][0]["outcomes"]["24h"]
        self.assertEqual(outcome["return_pct"], 10)
        self.assertEqual(outcome["elapsed_hours"], 24.5)
        advance(state, [row(price=500)], REGIME, "2026-09-24T02:01:00Z")
        self.assertEqual(state["observations"][0]["outcomes"]["7d"]["status"], "missed")
        self.assertEqual(report["groups"]["confirmation"]["4"]["horizons"]["7d"]["mean_return_pct"], None)

    def test_gaps_hold_and_new_episode(self):
        state, _ = advance({}, [row()], REGIME, "2026-09-17T00:00:00Z")
        for hour, rows in [(1, []), (2, [row(status="UNVERIFIED")]), (3, [row()])]:
            advance(state, rows, REGIME, f"2026-09-17T0{hour}:00:00Z")
        self.assertEqual(len(state["observations"]), 1)
        advance(state, [row(status="EVENT HOLD")], REGIME, "2026-09-17T04:00:00Z")
        advance(state, [row()], REGIME, "2026-09-17T05:00:00Z")
        self.assertEqual(len(state["observations"]), 2)

    def test_invalid_prices_and_no_zero_fill(self):
        for price in [None, 0, -1, float("nan"), float("inf")]:
            state, _ = advance({}, [row(price=price)], REGIME, "2026-09-17T00:00:00Z")
            self.assertEqual(state["observations"], [])
        state, _ = advance({}, [row()], REGIME, "2026-09-17T00:00:00Z")
        _, report = advance(state, [], REGIME, "2026-09-18T03:00:00Z")
        bucket = report["groups"]["confirmation"]["4"]["horizons"]["24h"]
        self.assertEqual(bucket["measured"], 0)
        self.assertEqual(bucket["missed"], 1)
        self.assertIsNone(bucket["mean_return_pct"])

    def test_repeat_timestamp_and_out_of_order(self):
        state, _ = advance({}, [row()], REGIME, "2026-09-17T00:00:00Z")
        advance(state, [row()], REGIME, "2026-09-17T00:00:00Z")
        self.assertEqual(len(state["observations"]), 1)
        with self.assertRaises(ValueError):
            advance(state, [row()], REGIME, "2026-09-16T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
