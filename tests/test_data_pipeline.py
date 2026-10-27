from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from anomaly_analysis import build_equipment_analysis
from database_manager import sync_production_data
from health_score import (
    calculate_health_score_from_anomalies,
    risk_level_from_score,
)
from production_source import (
    ProductionDataError,
    load_production_records,
)
from trend_analysis import analyze_health_trend


class ProductionSourceTests(unittest.TestCase):
    def test_default_csv_contains_all_three_equipment(self) -> None:
        records = load_production_records()
        equipment_ids = {
            record["equipment_id"] for record in records
        }

        self.assertEqual(len(records), 30)
        self.assertEqual(
            equipment_ids,
            {"ETCH-01", "ETCH-02", "ETCH-03"},
        )

    def test_example_json_file_is_runnable(self) -> None:
        records = load_production_records(
            Path(__file__).parents[1]
            / "data"
            / "production_data.example.json"
        )

        self.assertEqual(len(records), 3)
        self.assertEqual(
            {record["equipment_id"] for record in records},
            {"ETCH-DEMO-01", "ETCH-DEMO-02"},
        )

    def test_json_and_chinese_headers_are_supported(self) -> None:
        payload = {
            "records": [
                {
                    "批次编号": "JSON-BATCH-001",
                    "设备编号": "ETCH-X",
                    "工艺": "Etching",
                    "温度": "120 ℃",
                    "压力": "130 kPa",
                    "良率": "75%",
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "production.json"
            data_file.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            records = load_production_records(data_file)

        self.assertEqual(records[0]["batch_id"], "JSON-BATCH-001")
        self.assertEqual(records[0]["equipment_id"], "ETCH-X")
        self.assertEqual(records[0]["temperature_c"], 120.0)
        self.assertEqual(records[0]["yield_pct"], 75.0)

    def test_sync_writes_json_records_to_database(self) -> None:
        payload = {
            "records": [
                {
                    "batch_id": "JSON-BATCH-001",
                    "equipment_id": "ETCH-X",
                    "process": "Etching",
                    "temperature_c": 120,
                    "pressure_kpa": 130,
                    "yield_pct": 75,
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            data_file = temp_path / "production.json"
            database_file = temp_path / "production.db"
            data_file.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            result = sync_production_data(
                data_file=data_file,
                db_file=database_file,
                force=True,
            )

            with closing(sqlite3.connect(database_file)) as conn:
                rows = conn.execute(
                    """
                    SELECT batch_id, equipment_id, yield_pct
                    FROM wafer_production
                    """
                ).fetchall()

        self.assertTrue(result["synced"])
        self.assertEqual(rows, [("JSON-BATCH-001", "ETCH-X", 75.0)])

    def test_sync_refreshes_when_source_file_changes(self) -> None:
        first_batch = {
            "batch_id": "JSON-BATCH-001",
            "equipment_id": "ETCH-X",
            "process": "Etching",
            "temperature_c": 80,
            "pressure_kpa": 100,
            "yield_pct": 95,
        }
        second_batch = {
            "batch_id": "JSON-BATCH-002",
            "equipment_id": "ETCH-Y",
            "process": "Deposition",
            "temperature_c": 90,
            "pressure_kpa": 110,
            "yield_pct": 96,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            data_file = temp_path / "production.json"
            database_file = temp_path / "production.db"

            data_file.write_text(
                json.dumps([first_batch]),
                encoding="utf-8",
            )
            sync_production_data(data_file, database_file, force=True)

            unchanged = sync_production_data(data_file, database_file)

            data_file.write_text(
                json.dumps([first_batch, second_batch]),
                encoding="utf-8",
            )
            refreshed = sync_production_data(data_file, database_file)

            with closing(sqlite3.connect(database_file)) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM wafer_production"
                ).fetchone()[0]

        self.assertFalse(unchanged["synced"])
        self.assertTrue(refreshed["synced"])
        self.assertEqual(count, 2)

    def test_duplicate_batch_is_rejected(self) -> None:
        record = {
            "batch_id": "DUP-001",
            "equipment_id": "ETCH-X",
            "process": "Etching",
            "temperature_c": 80,
            "pressure_kpa": 100,
            "yield_pct": 95,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "production.json"
            data_file.write_text(
                json.dumps([record, record]),
                encoding="utf-8",
            )

            with self.assertRaises(ProductionDataError):
                load_production_records(data_file)


class AnalysisTests(unittest.TestCase):
    def test_equipment_statistics_and_scores(self) -> None:
        expected = {
            "ETCH-01": (100, 0, 7),
            "ETCH-02": (45, 3, 12),
            "ETCH-03": (100, 0, 11),
        }

        for equipment_id, (score, total, records) in expected.items():
            with self.subTest(equipment_id=equipment_id):
                analysis = build_equipment_analysis(equipment_id)
                calculated = calculate_health_score_from_anomalies(
                    analysis["anomalies"]
                )

                self.assertEqual(calculated, score)
                self.assertEqual(
                    risk_level_from_score(calculated),
                    (
                        "高风险"
                        if score < 60
                        else "关注"
                        if score < 80
                        else "正常"
                    ),
                )
                self.assertEqual(analysis["stats"]["total"], total)
                self.assertEqual(
                    analysis["stats"]["record_count"],
                    records,
                )
                self.assertEqual(
                    (
                        analysis["stats"]["temperature"]
                        + analysis["stats"]["pressure"]
                        + analysis["stats"]["yield"]
                    ),
                    analysis["stats"]["total"],
                )
                self.assertEqual(
                    (
                        analysis["stats"]["affected_batches"]
                        + analysis["stats"]["normal_batches"]
                    ),
                    records,
                )

    def test_etch_02_statistics_are_consistent(self) -> None:
        stats = build_equipment_analysis("ETCH-02")["stats"]

        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["temperature"], 1)
        self.assertEqual(stats["pressure"], 1)
        self.assertEqual(stats["yield"], 1)
        self.assertEqual(stats["affected_batches"], 3)
        self.assertEqual(stats["normal_batches"], 9)

    def test_stable_high_risk_trend_keeps_high_risk_level(self) -> None:
        trend = analyze_health_trend([45, 45, 45, 45, 45])

        self.assertEqual(trend["trend"], "稳定")
        self.assertEqual(trend["level"], "高风险")
        self.assertIn("高风险", trend["message"])

    def test_declining_trend(self) -> None:
        trend = analyze_health_trend([82, 75, 68, 55, 45])

        self.assertEqual(trend["trend"], "持续下降")
        self.assertEqual(trend["level"], "高风险")


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient

        import main_api

        cls.client = TestClient(main_api.app)

    def test_default_dashboard_uses_first_equipment_from_data(self) -> None:
        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertIn("ETCH-01", response.text)
        self.assertRegex(
            response.text,
            r'<option\s+value="ETCH-01"\s+selected',
        )
        self.assertIn('data-template-rendered="true"', response.text)

    def test_template_does_not_put_jinja_expressions_in_javascript(self) -> None:
        template = (
            Path(__file__).parents[1]
            / "templates"
            / "dashboard.html"
        ).read_text(encoding="utf-8")

        executable_scripts = re.findall(
            r"<script"
            r"(?![^>]*\bsrc=)"
            r"(?![^>]*application/json)"
            r"[^>]*>(.*?)</script>",
            template,
            re.DOTALL | re.IGNORECASE,
        )

        self.assertTrue(executable_scripts)
        for script in executable_scripts:
            self.assertNotIn("{{", script)
            self.assertNotIn("{%", script)

    def test_root_redirects_to_dashboard(self) -> None:
        response = self.client.get("/", follow_redirects=False)

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/dashboard")

    def test_health_check(self) -> None:
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_equipment_api_returns_all_devices(self) -> None:
        response = self.client.get("/api/equipment")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 3)
        self.assertEqual(
            {item["equipment"] for item in payload["items"]},
            {"ETCH-01", "ETCH-02", "ETCH-03"},
        )

    def test_equipment_analysis_api_matches_dashboard_rules(self) -> None:
        response = self.client.get("/api/equipment/ETCH-02/analysis")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["health_score"], 45)
        self.assertEqual(payload["risk_level"], "高风险")
        self.assertEqual(payload["stats"]["total"], 3)
        self.assertEqual(payload["stats"]["affected_batches"], 3)

    def test_data_source_api_reports_external_file(self) -> None:
        response = self.client.get("/api/data-source")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["name"], "production_data.csv")
        self.assertEqual(payload["format"], "CSV")
        self.assertEqual(payload["record_count"], 30)

    def test_dashboard_switches_equipment_data(self) -> None:
        response = self.client.get(
            "/dashboard",
            params={"equipment_id": "ETCH-02"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            '<div class="card-value">ETCH-02</div>',
            response.text,
        )
        self.assertRegex(
            response.text,
            r"异常事件总数</p>\s*<h3>3</h3>",
        )
        self.assertRegex(
            response.text,
            r"涉及异常批次</p>\s*<h3>3</h3>",
        )
        self.assertRegex(
            response.text,
            r'<option\s+value="ETCH-02"\s+selected',
        )

    def test_history_chart_and_trend_use_same_current_score(self) -> None:
        response = self.client.get("/health_history/ETCH-02")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["scores"]), 12)
        self.assertEqual(
            payload["scores"],
            [100, 85, 85, 85, 85, 85, 75, 45, 45, 45, 45, 45],
        )
        self.assertEqual(payload["trend"]["trend"], "持续下降")
        self.assertEqual(payload["trend"]["level"], "高风险")
        self.assertEqual(
            payload["trend"]["current_score"],
            payload["scores"][-1],
        )

    def test_normal_equipment_has_one_chart_point_per_batch(self) -> None:
        expected_counts = {
            "ETCH-01": 7,
            "ETCH-03": 11,
        }

        for equipment_id, point_count in expected_counts.items():
            with self.subTest(equipment_id=equipment_id):
                payload = self.client.get(
                    f"/health_history/{equipment_id}"
                ).json()

                self.assertEqual(len(payload["scores"]), point_count)
                self.assertEqual(payload["scores"], [100] * point_count)
                self.assertEqual(payload["trend"]["trend"], "稳定")
                self.assertEqual(payload["trend"]["level"], "正常")

    def test_dashboard_does_not_call_llm(self) -> None:
        import main_api

        original = main_api.generate_report
        main_api.generate_report = lambda _: (_ for _ in ()).throw(
            AssertionError("dashboard must not call the LLM")
        )

        try:
            response = self.client.get(
                "/dashboard",
                params={"equipment_id": "ETCH-03"},
            )
        finally:
            main_api.generate_report = original

        self.assertEqual(response.status_code, 200)
        self.assertIn("ETCH-03", response.text)

    def test_invalid_api_equipment_returns_404(self) -> None:
        response = self.client.get("/health/NOT-FOUND")

        self.assertEqual(response.status_code, 404)

    def test_invalid_dashboard_selection_falls_back_to_first(self) -> None:
        response = self.client.get(
            "/dashboard",
            params={"equipment_id": "NOT-FOUND"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            '<div class="card-value">ETCH-01</div>',
            response.text,
        )


if __name__ == "__main__":
    unittest.main()
