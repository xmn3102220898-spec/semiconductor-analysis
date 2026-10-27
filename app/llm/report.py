"""基于生产数据和知识库生成 DeepSeek 诊断报告。

大模型、向量模型和知识库采用懒加载，避免普通仪表盘请求或应用启动
时访问外部网络。
"""

from __future__ import annotations

import time
from typing import Any

from app.analysis.anomalies import build_equipment_analysis
from app.analysis.health import (
    calculate_health_score_from_anomalies,
    risk_level_from_score,
)
from app.config import settings
from app.observability import get_logger


logger = get_logger(__name__)

_client: Any = None
_documents: list[dict[str, Any]] | None = None
_embedding_model: Any = None
_embeddings: Any = None


def _get_client() -> Any:
    global _client

    if _client is None:
        from openai import OpenAI

        if not settings.deepseek_api_key:
            raise RuntimeError(
                "未配置 DEEPSEEK_API_KEY，无法生成大模型诊断报告。"
            )

        _client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )

    return _client


def _get_rag_resources() -> tuple[
    list[dict[str, Any]],
    Any,
    Any,
]:
    """首次调用报告时再加载知识库和向量模型。"""
    global _documents, _embedding_model, _embeddings

    if _documents is None or _embedding_model is None or _embeddings is None:
        from sentence_transformers import SentenceTransformer

        from app.rag.semantic import build_embeddings, load_documents

        _documents = load_documents()
        _embedding_model = SentenceTransformer(settings.embedding_model)
        _embeddings = build_embeddings(_documents, _embedding_model)

    return _documents, _embedding_model, _embeddings


def build_report_prompt(equipment_id: str) -> str:
    """组装包含生产数据、评分和 RAG 检索结果的分析提示词。"""
    from app.rag.semantic import search_knowledge

    analysis = build_equipment_analysis(equipment_id)
    anomalies = analysis["anomalies"]
    stats = analysis["stats"]
    score = calculate_health_score_from_anomalies(anomalies)
    risk_level = risk_level_from_score(score)

    anomaly_text = "\n".join(
        (
            f"批次：{item['batch_id']}；"
            f"异常类型：{item['type']}；"
            f"异常值：{item['value']}"
        )
        for item in anomalies
    )
    if not anomaly_text:
        anomaly_text = "当前规则未识别到异常事件。"

    question = (
        f"{equipment_id} 设备异常分析："
        f"{'、'.join(item['type'] for item in anomalies) or '无异常'}；"
        "温度、压力、良率"
    )

    documents, model, embeddings = _get_rag_resources()
    knowledge = search_knowledge(
        question,
        documents,
        embeddings,
        model,
    )
    logger.info(
        "knowledge_retrieval_completed",
        extra={
            "event": "knowledge_retrieval_completed",
            "equipment": equipment_id,
            "chunk_count": len(knowledge),
            "top_score": knowledge[0]["score"] if knowledge else None,
        },
    )
    knowledge_text = "\n".join(
        item["content"] for item in knowledge
    )

    return f"""
你是一名半导体设备分析工程师。

请根据以下模拟生产数据生成设备诊断报告。

设备：
{equipment_id}

健康评分：
{score}/100

风险等级：
{risk_level}

生产批次数量：
{stats['record_count']}

异常事件数量：
{stats['total']}

异常记录：
{anomaly_text}

参考知识：
{knowledge_text}

要求：
1. 输出结构化诊断报告。
2. 分析异常现象。
3. 给出可能原因。
4. 给出建议检查方向。
5. 不要编造真实工厂经验。
6. 明确说明数据来自模拟项目。
"""


def generate_report(equipment_id: str) -> str:
    """调用 DeepSeek 生成设备诊断报告。"""
    started_at = time.perf_counter()
    prompt = build_report_prompt(equipment_id)
    logger.info(
        "llm_report_started",
        extra={
            "event": "llm_report_started",
            "equipment": equipment_id,
            "prompt_chars": len(prompt),
            "model": settings.deepseek_model,
        },
    )

    try:
        response = _get_client().chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {
                    "role": "system",
                    "content": "你是一名半导体设备AI助手",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=settings.llm_temperature,
        )
    except Exception:
        logger.exception(
            "llm_report_failed",
            extra={
                "event": "llm_report_failed",
                "equipment": equipment_id,
                "duration_ms": round(
                    (time.perf_counter() - started_at) * 1000,
                    2,
                ),
            },
        )
        raise

    duration_ms = round(
        (time.perf_counter() - started_at) * 1000,
        2,
    )
    usage = getattr(response, "usage", None)
    logger.info(
        "llm_report_completed",
        extra={
            "event": "llm_report_completed",
            "equipment": equipment_id,
            "duration_ms": duration_ms,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(
                usage,
                "completion_tokens",
                None,
            ),
        },
    )

    return response.choices[0].message.content


if __name__ == "__main__":
    print(generate_report("ETCH-02"))
