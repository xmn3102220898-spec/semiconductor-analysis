"""Controlled LLM diagnosis with schema validation and deterministic fallback."""

from __future__ import annotations

import time
from typing import Any

from app.analysis.anomalies import build_equipment_analysis
from app.analysis.health import (
    build_health_score_breakdown,
    risk_level_from_score,
)
from app.config import settings
from app.data.history import record_llm_call
from app.llm.prompting import render_prompt
from app.llm.schema import (
    DiagnosticReportOutput,
    ReportValidationError,
    validate_diagnostic_report,
)
from app.observability import get_logger
from app.rag.pipeline import get_knowledge_pipeline


logger = get_logger(__name__)
_client: Any = None


def _get_client() -> Any:
    global _client
    if _client is None:
        from openai import OpenAI

        if not settings.deepseek_api_key:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY")
        _client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
    return _client


def _facts_and_retrieval(equipment_id: str) -> tuple[
    dict[str, Any],
    dict[str, Any],
    str,
]:
    analysis = build_equipment_analysis(equipment_id)
    anomalies = analysis["anomalies"]
    breakdown = build_health_score_breakdown(anomalies)
    score = breakdown["final_score"]
    risk_level = risk_level_from_score(score)
    question = (
        f"{equipment_id} 设备异常分析："
        f"{'、'.join(item['type'] for item in anomalies) or '无异常'}；"
        "温度、压力、良率、检查建议"
    )
    equipment_type = analysis["stats"]["equipment_type"]
    # 设备专属知识优先；通用（general）知识对任何设备都成立，必须保留。
    filters: dict[str, list[str]] = {
        "equipment_type": [equipment_type, "general"],
    }
    try:
        pipeline = get_knowledge_pipeline()
        retrieval = pipeline.search(
            question,
            top_k=settings.rag_top_k,
            filters=filters,
        )
        if not retrieval["hits"]:
            # 过滤后无命中时放宽，宁愿召回弱相关知识，也不要空上下文。
            relaxed = pipeline.search(
                question,
                top_k=settings.rag_top_k,
            )
            if relaxed["hits"]:
                retrieval = {
                    **relaxed,
                    "filters_relaxed": True,
                    "filters": filters,
                }
        retrieval.setdefault("filters_relaxed", False)
        contexts = pipeline.build_context(retrieval["hits"])
    except Exception:
        logger.exception(
            "rag_retrieval_failed_for_report",
            extra={
                "event": "rag_retrieval_failed_for_report",
                "equipment": equipment_id,
            },
        )
        retrieval = {
            "question": question,
            "strategy": "unavailable",
            "hits": [],
            "no_match": True,
            "filters": filters,
            "filters_relaxed": False,
            "score_distribution": [],
        }
        contexts = "无匹配知识依据。"
    batch_ids = [row[1] for row in analysis["records"]]
    chunk_ids = [hit["chunk_id"] for hit in retrieval["hits"]]
    facts = {
        "equipment_id": equipment_id,
        "health_score": score,
        "risk_level": risk_level,
        "simulated_data": True,
        "equipment_type": analysis["stats"]["equipment_type"],
        "thresholds": analysis["stats"]["thresholds"],
        "stats": analysis["stats"],
        "anomalies": anomalies,
        "score_breakdown": breakdown,
        "allowed_batch_ids": batch_ids,
        "allowed_chunk_ids": chunk_ids,
        "no_knowledge_match": retrieval["no_match"],
    }
    return facts, retrieval, contexts


def build_report_prompt(equipment_id: str) -> str:
    facts, _, contexts = _facts_and_retrieval(equipment_id)
    return render_prompt(facts, contexts)


def _relevant_chunk_ids(
    retrieval: dict[str, Any],
    metric: str,
) -> list[str]:
    matches = [
        hit["chunk_id"]
        for hit in retrieval["hits"]
        if hit["parameter_type"] in {metric, "general"}
    ]
    return matches[:2]


def _fallback_report(
    facts: dict[str, Any],
    retrieval: dict[str, Any],
    reason: str,
) -> DiagnosticReportOutput:
    anomalies = facts["anomalies"]
    findings = []
    checks = []
    category_map = {
        "temperature": "temperature",
        "pressure": "pressure",
        "yield": "yield",
    }

    for anomaly in anomalies:
        metric = anomaly["metric"]
        chunk_ids = _relevant_chunk_ids(retrieval, metric)
        findings.append({
            "category": category_map[metric],
            "summary": (
                f"{anomaly['batch_id']} 的 {anomaly['type']} "
                f"检测值为 {anomaly['value']}，阈值为 "
                f"{anomaly['threshold']:g}。"
            ),
            "batch_ids": [anomaly["batch_id"]],
            "chunk_ids": chunk_ids,
        })
        checks.append({
            "action": (
                f"优先核查 {anomaly['batch_id']} 对应参数的"
                "传感器、控制回路、报警记录和工艺设定值。"
            ),
            "priority": "high",
            "batch_ids": [anomaly["batch_id"]],
            "chunk_ids": chunk_ids,
        })

    if not findings:
        findings.append({
            "category": "process",
            "summary": "当前模拟数据未触发异常规则。",
            "batch_ids": [],
            "chunk_ids": (
                [retrieval["hits"][0]["chunk_id"]]
                if retrieval["hits"]
                else []
            ),
        })
    if not checks:
        checks.append({
            "action": (
                "继续监测关键参数，并结合设备报警和维护记录"
                "确认数据完整性。"
            ),
            "priority": "low",
            "batch_ids": [],
            "chunk_ids": (
                [retrieval["hits"][0]["chunk_id"]]
                if retrieval["hits"]
                else []
            ),
        })

    return DiagnosticReportOutput.model_validate({
        "equipment_id": facts["equipment_id"],
        "health_score": facts["health_score"],
        "risk_level": facts["risk_level"],
        "simulated_data": True,
        "summary": (
            f"{facts['equipment_id']} 共 {facts['stats']['record_count']} "
            f"个模拟批次，检测到 {facts['stats']['total']} 个异常事件，"
            f"健康评分 {facts['health_score']}，风险等级 "
            f"{facts['risk_level']}。"
        ),
        "findings": findings,
        "recommended_checks": checks,
        "limitations": [
            "大模型不可用或输出未通过校验，本报告由确定性规则降级生成。",
            reason,
            "生产数据、阈值和知识库均为模拟内容，需由具备资质的人员确认。",
        ],
    })


def render_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# {report['equipment_id']} 设备诊断报告",
        "",
        report["summary"],
        "",
        "## 分析结论",
    ]
    for finding in report["findings"]:
        citations = ", ".join(finding["chunk_ids"])
        suffix = f" [引用：{citations}]" if citations else ""
        lines.append(f"- {finding['summary']}{suffix}")
    lines.extend(["", "## 建议检查"])
    for check in report["recommended_checks"]:
        citations = ", ".join(check["chunk_ids"])
        suffix = f" [引用：{citations}]" if citations else ""
        lines.append(
            f"- [{check['priority']}] {check['action']}{suffix}"
        )
    lines.extend(["", "## 边界与限制"])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines)


def _response_tokens(response: Any) -> tuple[int | None, int | None]:
    usage = getattr(response, "usage", None)
    return (
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
    )


def generate_report_result(equipment_id: str) -> dict[str, Any]:
    started_at = time.perf_counter()
    facts, retrieval, contexts = _facts_and_retrieval(equipment_id)
    feedback = ""
    last_error = ""
    prompt_tokens_total = 0
    completion_tokens_total = 0
    structured: DiagnosticReportOutput | None = None
    provider = "rules_fallback"

    for attempt_index in range(settings.llm_max_retries + 1):
        prompt = render_prompt(facts, contexts, feedback)
        attempt_started = time.perf_counter()
        try:
            response = _get_client().chat.completions.create(
                model=settings.deepseek_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是半导体设备分析助手。"
                            "只输出符合 Schema 的 JSON。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=settings.llm_temperature,
                response_format={"type": "json_object"},
            )
            prompt_tokens, completion_tokens = _response_tokens(response)
            prompt_tokens_total += int(prompt_tokens or 0)
            completion_tokens_total += int(completion_tokens or 0)
            structured = validate_diagnostic_report(
                response.choices[0].message.content,
                facts,
            )
            provider = "deepseek"
            record_llm_call(
                equipment=equipment_id,
                provider=provider,
                success=True,
                fallback=False,
                latency_ms=(time.perf_counter() - attempt_started) * 1000,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            break
        except ReportValidationError as exc:
            last_error = str(exc)
            feedback = last_error
            record_llm_call(
                equipment=equipment_id,
                provider="deepseek_rejected",
                success=False,
                fallback=False,
                latency_ms=(time.perf_counter() - attempt_started) * 1000,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                validation_error=last_error,
            )
            logger.warning(
                "llm_report_rejected",
                extra={
                    "event": "llm_report_rejected",
                    "equipment": equipment_id,
                    "attempt": attempt_index + 1,
                    "validation_error": last_error,
                },
            )
        except Exception as exc:
            last_error = str(exc)
            logger.exception(
                "llm_report_failed",
                extra={
                    "event": "llm_report_failed",
                    "equipment": equipment_id,
                    "attempt": attempt_index + 1,
                },
            )
            break

    if structured is None:
        provider = "rules_fallback"
        structured = _fallback_report(
            facts,
            retrieval,
            last_error or "大模型不可用",
        )
        record_llm_call(
            equipment=equipment_id,
            provider=provider,
            success=True,
            fallback=True,
            latency_ms=(time.perf_counter() - started_at) * 1000,
            prompt_tokens=prompt_tokens_total or None,
            completion_tokens=completion_tokens_total or None,
            validation_error=last_error or "LLM_UNAVAILABLE",
        )

    structured_payload = structured.model_dump()
    references = [
        {
            "chunk_id": hit["chunk_id"],
            "source": hit["source"],
            "section": hit["section"],
            "score": hit["score"],
            "start_char": hit["start_char"],
            "end_char": hit["end_char"],
            "excerpt": hit["content"][:240],
        }
        for hit in retrieval["hits"]
    ]
    return {
        "report": render_report_markdown(structured_payload),
        "report_json": structured_payload,
        "references": references,
        "retrieval": retrieval,
        "provider": provider,
        "fallback": provider == "rules_fallback",
        "latency_ms": round(
            (time.perf_counter() - started_at) * 1000,
            3,
        ),
        "prompt_tokens": prompt_tokens_total,
        "completion_tokens": completion_tokens_total,
    }


def generate_report(equipment_id: str) -> str:
    """Backward-compatible report-only return value."""
    return generate_report_result(equipment_id)["report"]


if __name__ == "__main__":
    print(generate_report("ETCH-02"))
