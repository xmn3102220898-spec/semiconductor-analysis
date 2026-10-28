from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from anomaly_analysis import (
    build_equipment_analysis,
    calculate_risk,
    format_anomaly_result,
)
from database_manager import (
    create_database,
    get_connection,
    sync_production_data,
)
from health_score import (
    build_health_score_breakdown,
    calculate_batch_health_trend,
    calculate_health_score_from_anomalies,
    risk_level_from_score,
)
from production_source import (
    ProductionDataError,
    load_production_records,
    validate_production_file,
)
from trend_analysis import analyze_health_trend
from app.analysis.rules import (
    RuleConfigurationError,
    default_thresholds,
    load_rules,
    resolve_equipment_rules,
)


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

            with patch(
                "app.data.manager.load_production_records",
                side_effect=AssertionError(
                    "unchanged data must not be parsed again"
                ),
            ):
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

    def test_data_quality_report_collects_multiple_reasons(self) -> None:
        valid = {
            "batch_id": "QUALITY-001",
            "equipment_id": "ETCH-X",
            "process": "Etching",
            "temperature_c": 80,
            "pressure_kpa": 100,
            "yield_pct": 95,
        }
        payload = [
            valid,
            {**valid},
            {
                **valid,
                "batch_id": "QUALITY-002",
                "equipment_id": "etch-invalid",
            },
            {
                **valid,
                "batch_id": "QUALITY-003",
                "temperature_c": 900,
            },
            {
                **valid,
                "batch_id": "QUALITY-004",
                "process": "UnknownProcess",
            },
            {
                key: value
                for key, value in valid.items()
                if key != "yield_pct"
            }
            | {"batch_id": "QUALITY-005"},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "dirty.json"
            data_file.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            report = validate_production_file(data_file)

        self.assertFalse(report.healthy)
        self.assertEqual(report.total_records, 6)
        self.assertEqual(report.valid_records, 1)
        self.assertEqual(report.rejected_records, 5)
        self.assertEqual(report.reason_counts["duplicate_batch"], 1)
        self.assertEqual(report.reason_counts["equipment_id_invalid"], 1)
        self.assertEqual(
            report.reason_counts["temperature_out_of_range"],
            1,
        )
        self.assertEqual(report.reason_counts["process_not_allowed"], 1)
        self.assertEqual(report.reason_counts["missing_field"], 1)

    def test_invalid_source_does_not_modify_database(self) -> None:
        payload = [
            {
                "batch_id": "BAD-001",
                "equipment_id": "ETCH-X",
                "process": "Etching",
                "temperature_c": 900,
                "pressure_kpa": 100,
                "yield_pct": 95,
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            data_file = temp_path / "bad.json"
            database_file = temp_path / "production.db"
            data_file.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ProductionDataError):
                sync_production_data(data_file, database_file, force=True)

            with closing(sqlite3.connect(database_file)) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM wafer_production"
                ).fetchone()[0]

        self.assertEqual(count, 0)

    def test_empty_and_missing_column_files_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            empty_file = temp_path / "empty.csv"
            empty_file.write_text(
                "batch_id,equipment_id,process,"
                "temperature_c,pressure_kpa,yield_pct\n",
                encoding="utf-8",
            )
            empty_report = validate_production_file(empty_file)

            missing_column = temp_path / "missing.csv"
            missing_column.write_text(
                "batch_id,equipment_id,process,"
                "temperature_c,yield_pct\n"
                "MISSING-001,ETCH-X,Etching,80,95\n",
                encoding="utf-8",
            )
            missing_report = validate_production_file(missing_column)

        self.assertFalse(empty_report.healthy)
        self.assertEqual(
            empty_report.file_errors[0].code,
            "empty_file",
        )
        self.assertFalse(missing_report.healthy)
        self.assertEqual(missing_report.rejected_records, 1)
        self.assertEqual(
            missing_report.reason_counts["missing_field"],
            1,
        )

    def test_invalid_production_time_is_rejected(self) -> None:
        record = {
            "batch_id": "TIME-001",
            "equipment_id": "ETCH-X",
            "process": "Etching",
            "temperature_c": 80,
            "pressure_kpa": 100,
            "yield_pct": 95,
            "production_time": "not-a-time",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "invalid_time.json"
            data_file.write_text(
                json.dumps([record]),
                encoding="utf-8",
            )
            report = validate_production_file(data_file)

        self.assertFalse(report.healthy)
        self.assertEqual(report.reason_counts["invalid_time"], 1)

    def test_legacy_schema_is_migrated_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_file = Path(temp_dir) / "legacy.db"
            with closing(sqlite3.connect(database_file)) as conn:
                conn.execute(
                    """
                    CREATE TABLE wafer_production (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        batch_id TEXT NOT NULL,
                        equipment_id TEXT NOT NULL,
                        process TEXT NOT NULL,
                        temperature_c REAL NOT NULL,
                        pressure_kpa REAL NOT NULL,
                        yield_pct REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO wafer_production (
                        batch_id, equipment_id, process,
                        temperature_c, pressure_kpa, yield_pct
                    ) VALUES ('LEGACY-001', 'ETCH-X', 'Etching', 80, 100, 95)
                    """
                )
                conn.commit()

            create_database(database_file)

            with closing(
                get_connection(database_file)
            ) as conn:
                columns = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(wafer_production)"
                    )
                }
                indexes = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA index_list(wafer_production)"
                    )
                }
                count = conn.execute(
                    "SELECT COUNT(*) FROM wafer_production"
                ).fetchone()[0]

        self.assertIn("production_time", columns)
        self.assertIn("idx_wafer_equipment", indexes)
        self.assertIn("idx_wafer_batch", indexes)
        self.assertIn("idx_wafer_production_time", indexes)
        self.assertIn("idx_wafer_equipment_time", indexes)
        self.assertEqual(count, 1)

    def test_dirty_source_keeps_app_up_for_quality_report(self) -> None:
        dirty_payload = [
            {
                "batch_id": "BAD-001",
                "equipment_id": "ETCH-X",
                "process": "Etching",
                "temperature_c": 900,
                "pressure_kpa": 100,
                "yield_pct": 95,
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            data_file = temp_path / "dirty.json"
            database_file = temp_path / "production.db"
            diagnosis_file = temp_path / "diagnosis.db"
            data_file.write_text(
                json.dumps(dirty_payload),
                encoding="utf-8",
            )

            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]

            environment = os.environ.copy()
            environment.update({
                "PRODUCTION_DATA_FILE": str(data_file),
                "PRODUCTION_DB_FILE": str(database_file),
                "DIAGNOSIS_DB_FILE": str(diagnosis_file),
                "LOG_LEVEL": "CRITICAL",
            })
            creation_flags = getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "main_api:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=Path(__file__).parents[1],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )

            try:
                quality = None
                for _ in range(30):
                    time.sleep(0.2)
                    try:
                        with urlopen(
                            f"http://127.0.0.1:{port}/api/data-quality",
                            timeout=1,
                        ) as response:
                            quality = json.load(response)
                        break
                    except OSError:
                        continue

                self.assertIsNotNone(quality)
                self.assertFalse(quality["healthy"])
                self.assertEqual(quality["rejected_records"], 1)

                with self.assertRaises(HTTPError) as health_error:
                    urlopen(
                        f"http://127.0.0.1:{port}/healthz",
                        timeout=2,
                    )
                self.assertEqual(health_error.exception.code, 503)
            finally:
                process.terminate()
                process.wait(timeout=10)

            with closing(sqlite3.connect(database_file)) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM wafer_production"
                ).fetchone()[0]

        self.assertEqual(count, 0)


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

    def test_health_score_and_risk_boundaries(self) -> None:
        anomalies = [
            {"batch_id": "B-1", "type": "温度异常"},
            {"batch_id": "B-2", "type": "压力异常"},
            {"batch_id": "B-3", "type": "低良率异常"},
        ]

        self.assertEqual(
            calculate_health_score_from_anomalies(anomalies),
            45,
        )
        self.assertEqual(
            calculate_health_score_from_anomalies(
                [{"type": "未知异常"}]
            ),
            100,
        )
        self.assertEqual(
            calculate_health_score_from_anomalies(
                [{"type": "低良率异常"}] * 4
            ),
            0,
        )
        self.assertEqual(risk_level_from_score(80), "正常")
        self.assertEqual(risk_level_from_score(60), "关注")
        self.assertEqual(risk_level_from_score(59), "高风险")

    def test_score_breakdown_is_auditable(self) -> None:
        analysis = build_equipment_analysis("ETCH-02")
        breakdown = build_health_score_breakdown(
            analysis["anomalies"]
        )

        self.assertEqual(breakdown["base_score"], 100)
        self.assertEqual(breakdown["total_penalty"], 55)
        self.assertEqual(breakdown["final_score"], 45)
        self.assertEqual(len(breakdown["deductions"]), 3)
        self.assertEqual(
            [item["penalty"] for item in breakdown["deductions"]],
            [15, 10, 30],
        )

    def test_equipment_specific_rule_resolution(self) -> None:
        equipment_type, thresholds = resolve_equipment_rules("ETCH-02")

        self.assertEqual(equipment_type, "etch")
        self.assertEqual(thresholds.temperature_c, 100.0)
        self.assertEqual(thresholds.pressure_kpa, 120.0)
        self.assertEqual(thresholds.yield_pct, 90.0)

    def test_equipment_override_can_change_threshold(self) -> None:
        source = (
            Path(__file__).parents[1]
            / "config"
            / "analysis_rules.json"
        )
        rules = json.loads(source.read_text(encoding="utf-8"))
        rules["equipment_types"]["etch"]["pressure_kpa"] = 110.0
        rules["equipment_overrides"]["ETCH-02"] = {
            "temperature_c": 99.0
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            rule_file = Path(temp_dir) / "rules.json"
            rule_file.write_text(
                json.dumps(rules),
                encoding="utf-8",
            )
            _, thresholds = resolve_equipment_rules(
                "ETCH-02",
                str(rule_file),
            )

        self.assertEqual(thresholds.temperature_c, 99.0)
        self.assertEqual(thresholds.pressure_kpa, 110.0)

    def test_rule_file_errors_and_environment_overrides(self) -> None:
        source = (
            Path(__file__).parents[1]
            / "config"
            / "analysis_rules.json"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            with self.assertRaises(RuleConfigurationError):
                load_rules(str(temp_path / "missing.json"))

            invalid_json = temp_path / "invalid.json"
            invalid_json.write_text("{", encoding="utf-8")
            with self.assertRaises(RuleConfigurationError):
                load_rules(str(invalid_json))

            invalid_defaults = temp_path / "invalid_defaults.json"
            invalid_defaults.write_text(
                json.dumps({"default_thresholds": []}),
                encoding="utf-8",
            )
            with self.assertRaises(RuleConfigurationError):
                load_rules(str(invalid_defaults))

            invalid_pattern = json.loads(
                source.read_text(encoding="utf-8")
            )
            invalid_pattern["validation"]["equipment_id_pattern"] = "["
            invalid_pattern_file = temp_path / "invalid_pattern.json"
            invalid_pattern_file.write_text(
                json.dumps(invalid_pattern),
                encoding="utf-8",
            )
            with self.assertRaises(RuleConfigurationError):
                load_rules(str(invalid_pattern_file))

        load_rules.cache_clear()
        with patch.dict(
            "os.environ",
            {
                "TEMPERATURE_LIMIT": "101",
                "PRESSURE_LIMIT": "121",
                "YIELD_LIMIT": "91",
            },
        ):
            overridden = load_rules(str(source))
            self.assertEqual(overridden.defaults.temperature_c, 101.0)
            self.assertEqual(overridden.defaults.pressure_kpa, 121.0)
            self.assertEqual(overridden.defaults.yield_pct, 91.0)
        load_rules.cache_clear()

        self.assertEqual(default_thresholds().temperature_c, 100.0)

    def test_rules_file_wins_when_environment_is_unset(self) -> None:
        source = (
            Path(__file__).parents[1]
            / "config"
            / "analysis_rules.json"
        )
        rules = json.loads(source.read_text(encoding="utf-8"))
        rules["default_thresholds"]["temperature_c"] = 105.0
        rules["default_thresholds"]["pressure_kpa"] = 118.0

        with tempfile.TemporaryDirectory() as temp_dir:
            rule_file = Path(temp_dir) / "rules.json"
            rule_file.write_text(
                json.dumps(rules),
                encoding="utf-8",
            )
            without_overrides = {
                key: value
                for key, value in os.environ.items()
                if key
                not in {
                    "TEMPERATURE_LIMIT",
                    "PRESSURE_LIMIT",
                    "YIELD_LIMIT",
                }
            }
            load_rules.cache_clear()
            with patch.dict("os.environ", without_overrides, clear=True):
                loaded = load_rules(str(rule_file))
            load_rules.cache_clear()

        self.assertEqual(loaded.defaults.temperature_c, 105.0)
        self.assertEqual(loaded.defaults.pressure_kpa, 118.0)

    def test_batch_trend_applies_penalties_in_order(self) -> None:
        records = [
            (1, "B-001", "ETCH-X", "Etching", 80, 100, 95),
            (2, "B-002", "ETCH-X", "Etching", 120, 100, 95),
            (3, "B-003", "ETCH-X", "Etching", 80, 130, 80),
        ]
        anomalies = [
            {"batch_id": "B-002", "type": "温度异常"},
            {"batch_id": "B-003", "type": "压力异常"},
            {"batch_id": "B-003", "type": "低良率异常"},
        ]

        points = calculate_batch_health_trend(records, anomalies)

        self.assertEqual(
            [point["score"] for point in points],
            [100, 85, 45],
        )
        self.assertEqual(
            [point["penalty"] for point in points],
            [0, 15, 40],
        )

    def test_risk_and_anomaly_text_helpers(self) -> None:
        score, level = calculate_risk(
            [
                {"type": "低良率异常"},
                {"type": "温度异常"},
            ]
        )

        self.assertEqual(score, 80)
        self.assertEqual(level, "高风险")
        self.assertIn("ETCH-02", format_anomaly_result("ETCH-02"))

    def test_all_trend_branches(self) -> None:
        self.assertEqual(
            analyze_health_trend([70, 70])["level"],
            "关注",
        )
        self.assertEqual(
            analyze_health_trend([80, 90])["trend"],
            "回升",
        )
        self.assertEqual(
            analyze_health_trend(["bad", 90])["trend"],
            "数据不足",
        )
        self.assertEqual(
            analyze_health_trend([101, 90])["trend"],
            "数据不足",
        )


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
        self.assertIn("暂无已保存的诊断报告", template)
        self.assertIn("统一 RAG 检索已接入", template)

    def test_root_redirects_to_dashboard(self) -> None:
        response = self.client.get("/", follow_redirects=False)

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/dashboard")

    def test_openapi_contains_all_documented_endpoints(self) -> None:
        response = self.client.get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        paths = set(response.json()["paths"])
        required = {
            "/",
            "/healthz",
            "/api/data-source",
            "/api/data-quality",
            "/api/production/records",
            "/api/knowledge/search",
            "/api/knowledge/status",
            "/api/llm-stats",
            "/knowledge/chunk/{chunk_id}",
            "/diagnosis_detail/{record_id}",
            "/api/equipment",
            "/api/equipment/{equipment_id}/analysis",
            "/dashboard",
            "/health/{equipment_id}",
            "/health_history/{equipment_id}",
            "/diagnose/{equipment_id}",
            "/history",
            "/diagnosis_detail/{record_id}",
        }
        self.assertTrue(required.issubset(paths))
        self.assertIn(
            "post",
            response.json()["paths"]["/diagnose/{equipment_id}"],
        )

    def test_history_and_detail_pages_are_covered(self) -> None:
        history = self.client.get(
            "/history",
            params={"equipment_id": "ETCH-02"},
        )
        self.assertEqual(history.status_code, 200)
        self.assertIn("设备历史诊断记录", history.text)

        import app.api.main as api_module

        detail = {
            "equipment": "ETCH-02",
            "health_score": 45,
            "risk_level": "高风险",
            "report_text": "# report",
            "time": "2026-01-01 00:00:00",
            "references": [],
            "report_json": None,
            "provider": "rules_fallback",
            "fallback": True,
        }
        with patch.object(
            api_module,
            "get_diagnosis_detail",
            return_value=detail,
        ):
            response = self.client.get("/diagnosis_detail/1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("规则降级", response.text)

    def test_valid_health_endpoint(self) -> None:
        response = self.client.get("/health/ETCH-02")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["health_score"], 45)

    def test_knowledge_search_failure_returns_503(self) -> None:
        with patch(
            "app.api.main.get_knowledge_pipeline",
            side_effect=RuntimeError("index unavailable"),
        ):
            response = self.client.get(
                "/api/knowledge/search",
                params={"question": "温度异常"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["error"]["code"],
            "SERVICE_UNAVAILABLE",
        )

    def test_knowledge_search_api_returns_citations(self) -> None:
        fake_pipeline = SimpleNamespace(
            search=lambda question, top_k, filters: {
                "question": question,
                "strategy": "hybrid_vector_bm25",
                "filters": filters,
                "no_match": False,
                "score_distribution": [0.88],
                "hits": [
                    {
                        "chunk_id": "chunk-test-1",
                        "source": "equipment_alarm.txt",
                        "section": "温度过高",
                        "content": "检查温度传感器。",
                        "parameter_type": "temperature",
                        "equipment_type": "general",
                        "score": 0.88,
                    }
                ],
            },
            status=lambda: {"chunk_count": 1},
            get_chunk=lambda chunk_id: {
                "chunk_id": chunk_id,
                "title": "设备异常排查参考",
                "section": "温度过高",
                "source": "equipment_alarm.txt",
                "content": "检查温度传感器。",
                "start_char": 0,
                "end_char": 20,
                "parameter_type": "temperature",
                "equipment_type": "general",
            },
        )

        with patch(
            "app.api.main.get_knowledge_pipeline",
            return_value=fake_pipeline,
        ):
            response = self.client.get(
                "/api/knowledge/search",
                params={"question": "温度异常怎么检查"},
            )
            status = self.client.get("/api/knowledge/status")
            chunk = self.client.get(
                "/knowledge/chunk/chunk-test-1"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["data"]["hits"][0]["chunk_id"],
            "chunk-test-1",
        )
        self.assertTrue(payload["meta"]["request_id"])
        self.assertEqual(status.status_code, 200)
        self.assertEqual(
            status.json()["data"]["chunk_count"],
            1,
        )
        self.assertEqual(chunk.status_code, 200)
        self.assertIn("chunk-test-1", chunk.text)

    def test_llm_stats_api(self) -> None:
        stats = {
            "attempts": 3,
            "successes": 2,
            "fallbacks": 1,
        }
        with patch(
            "app.api.main.get_llm_call_stats",
            return_value=stats,
        ):
            response = self.client.get("/api/llm-stats")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], stats)

    def test_health_check(self) -> None:
        response = self.client.get(
            "/healthz",
            headers={"X-Request-ID": "p1a-request-id"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(
            response.headers["X-Request-ID"],
            "p1a-request-id",
        )

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
        self.assertEqual(
            payload["stats"]["thresholds"]["temperature_c"],
            100.0,
        )
        self.assertEqual(payload["stats"]["equipment_type"], "etch")
        self.assertEqual(
            payload["score_breakdown"]["total_penalty"],
            55,
        )

    def test_data_source_api_reports_external_file(self) -> None:
        response = self.client.get("/api/data-source")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["name"], "production_data.csv")
        self.assertEqual(payload["format"], "CSV")
        self.assertEqual(payload["record_count"], 30)

    def test_data_quality_api_reports_healthy_source(self) -> None:
        response = self.client.get("/api/data-quality")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["healthy"])
        self.assertEqual(payload["total_records"], 30)
        self.assertEqual(payload["rejected_records"], 0)

    def test_production_records_support_filters_and_pagination(self) -> None:
        response = self.client.get(
            "/api/production/records",
            params={
                "sort_by": "batch_id",
                "order": "asc",
                "page": 2,
                "page_size": 5,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["pagination"]["total"], 30)
        self.assertEqual(payload["pagination"]["total_pages"], 6)
        self.assertEqual(
            [item["batch_id"] for item in payload["items"]],
            [
                "BATCH-006",
                "BATCH-007",
                "BATCH-008",
                "BATCH-009",
                "BATCH-010",
            ],
        )

        filtered = self.client.get(
            "/api/production/records",
            params={
                "equipment_id": "ETCH-02",
                "start_time": "2026-09-10T00:00:00",
                "end_time": "2026-09-12T23:59:59",
                "sort_by": "production_time",
                "order": "asc",
            },
        ).json()["data"]
        self.assertEqual(filtered["pagination"]["total"], 3)
        self.assertEqual(
            [item["batch_id"] for item in filtered["items"]],
            ["BATCH-010", "BATCH-011", "BATCH-012"],
        )
        self.assertEqual(
            filtered["items"][0]["production_time"],
            "2026-09-10 08:00:00",
        )

    def test_production_records_reject_invalid_query_parameters(self) -> None:
        invalid_range = self.client.get(
            "/api/production/records",
            params={
                "start_time": "2026-09-20T00:00:00",
                "end_time": "2026-09-10T00:00:00",
            },
        )
        self.assertEqual(invalid_range.status_code, 400)
        self.assertEqual(
            invalid_range.json()["error"]["code"],
            "INVALID_TIME_RANGE",
        )

        invalid_sort = self.client.get(
            "/api/production/records",
            params={"sort_by": "id"},
        )
        self.assertEqual(invalid_sort.status_code, 422)

        invalid_page = self.client.get(
            "/api/production/records",
            params={"page": 0},
        )
        self.assertEqual(invalid_page.status_code, 422)

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
        self.assertIn("温度 &gt; 100.0℃", response.text)
        self.assertIn("<th>规则扣分</th>", response.text)
        self.assertIn("最近诊断报告", response.text)
        self.assertIn("检索引用", response.text)

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
        import app.api.main as api_module

        original = api_module.llm_reporter.generate_report
        api_module.llm_reporter.generate_report = (
            lambda _: (_ for _ in ()).throw(
                AssertionError("dashboard must not call the LLM")
            )
        )

        try:
            response = self.client.get(
                "/dashboard",
                params={"equipment_id": "ETCH-03"},
            )
        finally:
            api_module.llm_reporter.generate_report = original

        self.assertEqual(response.status_code, 200)
        self.assertIn("ETCH-03", response.text)

    def test_diagnose_returns_retrieval_references(self) -> None:
        import app.api.main as api_module

        reference = {
            "chunk_id": "chunk-123",
            "source": "equipment_alarm.txt",
            "section": "温度过高",
            "score": 0.91,
            "start_char": 10,
            "end_char": 50,
            "excerpt": "检查温度传感器。",
        }
        report_result = {
            "report": "模拟报告",
            "report_json": {
                "equipment_id": "ETCH-02",
                "health_score": 45,
                "risk_level": "高风险",
            },
            "references": [reference],
            "retrieval": {
                "strategy": "hybrid_vector_bm25",
                "hits": [reference],
                "no_match": False,
            },
            "provider": "deepseek",
            "fallback": False,
            "latency_ms": 1.0,
            "prompt_tokens": 10,
            "completion_tokens": 20,
        }

        with patch.object(
            api_module.llm_reporter,
            "generate_report_result",
            return_value=report_result,
        ), patch.object(api_module, "save_diagnosis") as save_mock:
            response = self.client.get("/diagnose/ETCH-02")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["references"][0]["chunk_id"],
            "chunk-123",
        )
        self.assertEqual(payload["report"], "模拟报告")
        self.assertEqual(payload["provider"], "deepseek")
        self.assertFalse(payload["fallback"])
        self.assertFalse(payload["persisted"])
        save_mock.assert_not_called()

    def test_post_diagnose_persists_history(self) -> None:
        import app.api.main as api_module

        report_result = {
            "report": "模拟报告",
            "report_json": {"equipment_id": "ETCH-02"},
            "references": [],
            "retrieval": {
                "strategy": "hybrid_vector_bm25",
                "hits": [],
                "no_match": True,
            },
            "provider": "rule-fallback",
            "fallback": True,
            "latency_ms": 1.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

        with patch.object(
            api_module.llm_reporter,
            "generate_report_result",
            return_value=report_result,
        ), patch.object(api_module, "save_diagnosis") as save_mock:
            response = self.client.post("/diagnose/ETCH-02")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["persisted"])
        save_mock.assert_called_once()

    def test_post_diagnose_reports_skipped_persist(self) -> None:
        """去重跳过时 persisted 必须是 False，不能只反映“请求了落库”。"""

        import app.api.main as api_module

        report_result = {
            "report": "模拟报告",
            "report_json": {"equipment_id": "ETCH-02"},
            "references": [],
            "retrieval": {
                "strategy": "hybrid_vector_bm25",
                "hits": [],
                "no_match": True,
            },
            "provider": "rule-fallback",
            "fallback": True,
            "latency_ms": 1.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

        with patch.object(
            api_module.llm_reporter,
            "generate_report_result",
            return_value=report_result,
        ), patch.object(api_module, "save_diagnosis", return_value=False):
            response = self.client.post("/diagnose/ETCH-02")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["persisted"])

    def test_save_diagnosis_reports_deduplicated_write(self) -> None:
        from app.data import history

        with tempfile.TemporaryDirectory() as temp_dir:
            database_file = Path(temp_dir) / "history.db"
            with patch.object(history, "DB_NAME", database_file):
                history.init_database()
                first = history.save_diagnosis(
                    "ETCH-02", 45, "高风险", "首次报告"
                )
                second = history.save_diagnosis(
                    "ETCH-02", 45, "高风险", "同分同风险，应被去重"
                )
                changed = history.save_diagnosis(
                    "ETCH-02", 80, "关注", "评分变化，应写入"
                )

            self.assertTrue(first)
            self.assertFalse(second)
            self.assertTrue(changed)

            with closing(sqlite3.connect(database_file)) as conn:
                rows = conn.execute(
                    "SELECT health_score FROM diagnosis_history ORDER BY id"
                ).fetchall()

        self.assertEqual([row[0] for row in rows], [45, 80])

    def test_invalid_api_equipment_returns_404(self) -> None:
        response = self.client.get("/health/NOT-FOUND")

        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertIn("detail", payload)
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")
        self.assertTrue(payload["error"]["request_id"])

    def test_invalid_path_parameter_returns_structured_422(self) -> None:
        response = self.client.get("/diagnosis_detail/not-an-integer")

        self.assertEqual(response.status_code, 422)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("detail", payload)

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
