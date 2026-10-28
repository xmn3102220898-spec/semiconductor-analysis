from __future__ import annotations

import json
import unittest
from pathlib import Path

from anomaly_analysis import build_equipment_analysis
from health_score import (
    calculate_batch_health_trend,
    risk_level_from_score,
)
from production_source import validate_production_file


ROOT = Path(__file__).parents[1]


class FixedDatasetRegressionTests(unittest.TestCase):
    def test_scores_and_quality_match_fixture(self) -> None:
        expected = json.loads(
            (ROOT / "tests" / "fixtures" / "expected_regression.json")
            .read_text(encoding="utf-8")
        )
        quality = validate_production_file().as_dict()

        self.assertEqual(
            {
                key: quality[key]
                for key in ("total_records", "valid_records", "rejected_records")
            },
            expected["data_quality"],
        )

        for equipment_id, item in expected["equipment"].items():
            with self.subTest(equipment_id=equipment_id):
                analysis = build_equipment_analysis(equipment_id)
                trend = calculate_batch_health_trend(
                    analysis["records"],
                    analysis["anomalies"],
                )
                scores = [point["score"] for point in trend]
                self.assertEqual(
                    scores[-1],
                    item["health_score"],
                )
                self.assertEqual(
                    risk_level_from_score(scores[-1]),
                    item["risk_level"],
                )
                self.assertEqual(
                    analysis["stats"]["record_count"],
                    item["record_count"],
                )
                self.assertEqual(
                    analysis["stats"]["total"],
                    item["anomaly_events"],
                )
                if "affected_batches" in item:
                    self.assertEqual(
                        analysis["stats"]["affected_batches"],
                        item["affected_batches"],
                    )
                if "trend_scores" in item:
                    self.assertEqual(scores, item["trend_scores"])


if __name__ == "__main__":
    unittest.main()
