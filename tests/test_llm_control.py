from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.llm.schema import (
    ReportValidationError,
    validate_diagnostic_report,
)
import app.data.history as history
import app.llm.report as report_module


def valid_output() -> dict:
    return {
        "equipment_id": "ETCH-02",
        "health_score": 45,
        "risk_level": "高风险",
        "simulated_data": True,
        "summary": "ETCH-02 出现多个模拟异常事件。",
        "findings": [
            {
                "category": "temperature",
                "summary": "BATCH-005 温度超过阈值。",
                "batch_ids": ["BATCH-005"],
                "chunk_ids": ["chunk-1"],
            }
        ],
        "recommended_checks": [
            {
                "action": "核查温度传感器和温控系统。",
                "priority": "high",
                "batch_ids": ["BATCH-005"],
                "chunk_ids": ["chunk-1"],
            }
        ],
        "limitations": ["这是模拟数据。"],
    }


def valid_facts() -> dict:
    return {
        "equipment_id": "ETCH-02",
        "health_score": 45,
        "risk_level": "高风险",
        "simulated_data": True,
        "allowed_batch_ids": [
            "BATCH-003",
            "BATCH-005",
        ],
        "allowed_chunk_ids": ["chunk-1"],
    }


def retrieval_payload() -> dict:
    hit = {
        "chunk_id": "chunk-1",
        "source": "equipment_alarm.txt",
        "section": "温度过高",
        "title": "设备异常排查参考",
        "content": "检查温度传感器和温控系统。",
        "parameter_type": "temperature",
        "equipment_type": "general",
        "topic": "equipment_alarm",
        "start_char": 0,
        "end_char": 20,
        "score": 0.9,
        "vector_score": 0.8,
        "keyword_score": 0.7,
    }
    return {
        "question": "ETCH-02 温度异常",
        "strategy": "hybrid_vector_bm25",
        "hits": [hit],
        "no_match": False,
        "score_distribution": [0.9],
        "filters": {},
    }


def fake_pipeline() -> object:
    return SimpleNamespace(
        search=lambda question, top_k, filters=None: retrieval_payload(),
        build_context=lambda hits: "[chunk_id=chunk-1] 温度排查",
    )


class OutputValidationTests(unittest.TestCase):
    def test_valid_output_passes(self) -> None:
        report = validate_diagnostic_report(
            json.dumps(valid_output(), ensure_ascii=False),
            valid_facts(),
        )

        self.assertEqual(report.equipment_id, "ETCH-02")
        self.assertEqual(report.findings[0].chunk_ids, ["chunk-1"])

    def test_hallucinated_batch_is_rejected(self) -> None:
        payload = valid_output()
        payload["findings"][0]["batch_ids"] = ["BATCH-999"]
        payload["findings"][0]["summary"] = "BATCH-999 温度异常。"

        with self.assertRaises(ReportValidationError) as context:
            validate_diagnostic_report(
                json.dumps(payload, ensure_ascii=False),
                valid_facts(),
            )

        self.assertIn("BATCH-999", str(context.exception))

    def test_wrong_score_and_chunk_are_rejected(self) -> None:
        payload = valid_output()
        payload["health_score"] = 100
        payload["findings"][0]["chunk_ids"] = ["fake-chunk"]

        with self.assertRaises(ReportValidationError) as context:
            validate_diagnostic_report(
                json.dumps(payload, ensure_ascii=False),
                valid_facts(),
            )

        message = str(context.exception)
        self.assertIn("health_score", message)
        self.assertIn("fake-chunk", message)

    def test_code_fence_json_is_supported(self) -> None:
        raw = f"```json\n{json.dumps(valid_output(), ensure_ascii=False)}\n```"
        report = validate_diagnostic_report(raw, valid_facts())
        self.assertEqual(report.risk_level, "高风险")


class ControlledReportTests(unittest.TestCase):
    def test_offline_llm_falls_back_to_rules(self) -> None:
        with patch.object(
            report_module,
            "get_knowledge_pipeline",
            return_value=fake_pipeline(),
        ), patch.object(
            report_module,
            "_get_client",
            side_effect=RuntimeError("offline"),
        ), patch.object(
            report_module,
            "record_llm_call",
        ) as record:
            result = report_module.generate_report_result("ETCH-02")

        self.assertTrue(result["fallback"])
        self.assertEqual(result["provider"], "rules_fallback")
        self.assertEqual(
            result["report_json"]["equipment_id"],
            "ETCH-02",
        )
        self.assertEqual(
            result["report_json"]["health_score"],
            45,
        )
        self.assertTrue(record.called)

    def test_rag_and_llm_failure_still_returns_rule_report(self) -> None:
        broken_pipeline = SimpleNamespace(
            search=lambda question, top_k, filters=None: (_ for _ in ()).throw(
                RuntimeError("embedding unavailable")
            ),
            build_context=lambda hits: "",
        )
        with patch.object(
            report_module,
            "get_knowledge_pipeline",
            return_value=broken_pipeline,
        ), patch.object(
            report_module,
            "_get_client",
            side_effect=RuntimeError("offline"),
        ), patch.object(
            report_module,
            "record_llm_call",
        ):
            result = report_module.generate_report_result("ETCH-02")

        self.assertTrue(result["fallback"])
        self.assertTrue(result["retrieval"]["no_match"])
        self.assertEqual(
            result["report_json"]["health_score"],
            45,
        )

    def test_invalid_output_retries_and_uses_valid_second_response(
        self,
    ) -> None:
        calls = 0
        invalid = valid_output()
        invalid["findings"][0]["batch_ids"] = ["BATCH-999"]

        class Completions:
            def create(self, **kwargs):
                nonlocal calls
                calls += 1
                content = (
                    json.dumps(invalid, ensure_ascii=False)
                    if calls == 1
                    else json.dumps(valid_output(), ensure_ascii=False)
                )
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=content)
                        )
                    ],
                    usage=SimpleNamespace(
                        prompt_tokens=100,
                        completion_tokens=50,
                    ),
                )

        client = SimpleNamespace(
            chat=SimpleNamespace(completions=Completions())
        )
        with patch.object(
            report_module,
            "get_knowledge_pipeline",
            return_value=fake_pipeline(),
        ), patch.object(
            report_module,
            "_get_client",
            return_value=client,
        ), patch.object(
            report_module,
            "record_llm_call",
        ):
            result = report_module.generate_report_result("ETCH-02")

        self.assertEqual(calls, 2)
        self.assertFalse(result["fallback"])
        self.assertEqual(result["provider"], "deepseek")
        self.assertEqual(result["prompt_tokens"], 200)
        self.assertEqual(result["completion_tokens"], 100)


class LlmStatsTests(unittest.TestCase):
    def test_call_stats_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_file = Path(temp_dir) / "stats.db"
            with patch.object(history, "DB_NAME", database_file):
                history.init_database()
                history.record_llm_call(
                    "ETCH-02",
                    "deepseek",
                    True,
                    False,
                    120.0,
                    prompt_tokens=100,
                    completion_tokens=50,
                )
                history.record_llm_call(
                    "ETCH-02",
                    "rules_fallback",
                    True,
                    True,
                    40.0,
                    validation_error="offline",
                )
                stats = history.get_llm_call_stats()

        self.assertEqual(stats["attempts"], 2)
        self.assertEqual(stats["successes"], 2)
        self.assertEqual(stats["fallbacks"], 1)
        self.assertEqual(stats["prompt_tokens"], 100)
        self.assertEqual(stats["completion_tokens"], 50)
        self.assertAlmostEqual(stats["fallback_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
