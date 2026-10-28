"""半导体设备 AI 诊断系统 FastAPI 入口。"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.analysis.anomalies import build_equipment_analysis
from app.analysis.health import (
    build_health_score_breakdown,
    calculate_batch_health_trend,
    risk_level_from_score,
)
from app.analysis.trend import analyze_health_trend
from app.config import settings
from app.data.equipment import get_equipment_ids
from app.data.history import (
    get_diagnosis_detail,
    get_diagnosis_records,
    get_llm_call_stats,
    init_database,
    save_diagnosis,
)
from app.data.manager import create_database, sync_production_data
from app.data.query import (
    query_production_records,
    query_record_count,
)
from app.errors import (
    AppError,
    app_error_handler,
    register_exception_handlers,
    unexpected_error_response,
)
from app.llm import report as llm_reporter
from app.rag.pipeline import get_knowledge_pipeline
from app.observability import (
    configure_logging,
    get_logger,
    get_request_id,
    normalize_request_id,
    reset_request_id,
    set_request_id,
)
from app.data.source import (
    ProductionDataError,
    summarize_source,
    validate_production_file,
)


configure_logging()

BASE_DIR = settings.project_root
logger = get_logger(__name__)

app = FastAPI(
    title=settings.app_name,
    description="基于 Python、RAG 和 DeepSeek 的设备分析平台",
    version=settings.version,
)

register_exception_handlers(app)


async def production_data_exception_handler(
    request: Request,
    exc: ProductionDataError,
) -> JSONResponse:
    return await app_error_handler(
        request,
        AppError(
            "PRODUCTION_DATA_UNAVAILABLE",
            str(exc),
            status_code=503,
        ),
    )


app.add_exception_handler(
    ProductionDataError,
    production_data_exception_handler,
)

templates = Jinja2Templates(directory=str(settings.templates_dir))


@app.middleware("http")
async def request_context_middleware(
    request: Request,
    call_next: Any,
) -> Any:
    """Attach a request_id to logs and response headers."""
    request_id = normalize_request_id(
        request.headers.get(settings.request_id_header)
    )
    token = set_request_id(request_id)
    request.state.request_id = request_id
    started_at = time.perf_counter()
    response = None

    try:
        response = await call_next(request)
        response.headers[settings.request_id_header] = request_id
        return response
    except Exception:
        logger.exception(
            "unhandled_exception",
            extra={
                "event": "unhandled_exception",
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
            },
        )
        response = unexpected_error_response()
        response.headers[settings.request_id_header] = request_id
        return response
    finally:
        logger.info(
            "http_request",
            extra={
                "event": "http_request",
                "method": request.method,
                "path": request.url.path,
                "status_code": (
                    response.status_code if response is not None else 500
                ),
                "duration_ms": round(
                    (time.perf_counter() - started_at) * 1000,
                    2,
                ),
            },
        )
        reset_request_id(token)


def _initialize_storage() -> None:
    create_database()
    init_database()
    sync_production_data()


try:
    _initialize_storage()
except ProductionDataError:
    logger.exception(
        "production_data_unavailable_at_startup",
        extra={
            "event": "production_data_unavailable_at_startup",
            "reason": "production_data_error",
        },
    )
except Exception:
    logger.exception(
        "application_initialization_failed",
        extra={
            "event": "application_initialization_failed",
            "reason": "unexpected_error",
        },
    )
    raise


def get_available_equipment() -> list[str]:
    try:
        equipment_ids = get_equipment_ids()
    except ProductionDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not equipment_ids:
        raise HTTPException(
            status_code=503,
            detail="生产数据文件中没有可用设备。",
        )

    return equipment_ids


def resolve_equipment_id(requested: str | None) -> str:
    """选择有效设备；没有指定或编号失效时使用数据中的第一台设备。"""
    equipment_ids = get_available_equipment()
    if requested in equipment_ids:
        return requested
    return equipment_ids[0]


def validate_equipment(equipment_id: str) -> None:
    if equipment_id not in get_available_equipment():
        raise HTTPException(
            status_code=404,
            detail=f"未找到设备：{equipment_id}",
        )


def get_risk_level(score: int | float) -> str:
    """兼容原接口名称。"""
    return risk_level_from_score(score)


def get_trend_series(
    equipment_id: str,
    current_score: int,
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按生产批次顺序生成累计健康评分趋势。"""
    if analysis is None:
        analysis = build_equipment_analysis(equipment_id)

    points = calculate_batch_health_trend(
        analysis["records"],
        analysis["anomalies"],
    )
    batch_ids = [point["batch_id"] for point in points]
    scores = [point["score"] for point in points]

    # 正常情况下累计评分末点已经等于当前总评分。
    # 保留该保护分支，便于以后调整评分规则时及时发现不一致。
    if not scores or scores[-1] != current_score:
        batch_ids.append("当前")
        scores.append(current_score)

    if len(scores) >= 2:
        trend = analyze_health_trend(scores)
    elif scores:
        trend = {
            "trend": "数据不足",
            "level": risk_level_from_score(scores[-1]),
            "message": "当前只有一个生产批次，暂时无法判断变化趋势。",
            "start_score": scores[-1],
            "current_score": scores[-1],
            "change": 0,
        }
    else:
        trend = {
            "trend": "暂无趋势",
            "level": "暂无数据",
            "message": "当前设备暂无有效评分。",
            "start_score": None,
            "current_score": None,
            "change": None,
        }

    return {
        "days": batch_ids,
        "batch_ids": batch_ids,
        "label_type": "batch",
        "scores": scores,
        "history_count": len(points),
        "point_count": len(points),
        "trend": trend,
    }


def get_source_info() -> dict[str, str]:
    source = summarize_source()
    source_path = Path(source["path"])
    source["updated_at"] = datetime.fromtimestamp(
        source_path.stat().st_mtime
    ).strftime("%Y-%m-%d %H:%M:%S")
    return source


@app.get("/health_history/{equipment_id}")
def health_history(equipment_id: str) -> dict[str, Any]:
    validate_equipment(equipment_id)

    analysis = build_equipment_analysis(equipment_id)
    score_breakdown = build_health_score_breakdown(
        analysis["anomalies"]
    )
    score = score_breakdown["final_score"]
    return get_trend_series(equipment_id, score, analysis=analysis)


@app.get("/")
def root() -> RedirectResponse:
    """浏览器入口跳转到设备仪表盘。"""
    return RedirectResponse(url="/dashboard")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """供本地运行或工业软件部署环境做存活检查。"""
    get_available_equipment()
    return {"status": "ok"}


@app.get("/api/data-source")
def api_data_source() -> dict[str, Any]:
    """返回当前生产数据文件及同步状态。"""
    source = get_source_info()
    source["record_count"] = query_record_count()
    return source


@app.get("/api/data-quality")
def api_data_quality() -> dict[str, Any]:
    """Validate the current source without modifying the SQLite cache."""
    return validate_production_file().as_dict()


@app.get("/api/knowledge/search")
def api_knowledge_search(
    question: str = Query(min_length=2, max_length=500),
    top_k: int = Query(default=4, ge=1, le=10),
    source: str | None = Query(default=None),
    equipment_type: str | None = Query(default=None),
    parameter_type: str | None = Query(default=None),
) -> dict[str, Any]:
    """Search the unified hybrid knowledge index."""
    filters = {
        key: value
        for key, value in {
            "source": source,
            "equipment_type": equipment_type,
            "parameter_type": parameter_type,
        }.items()
        if value
    }
    try:
        result = get_knowledge_pipeline().search(
            question,
            top_k=top_k,
            filters=filters,
        )
    except Exception as exc:
        logger.exception(
            "knowledge_search_failed",
            extra={"event": "knowledge_search_failed"},
        )
        raise HTTPException(
            status_code=503,
            detail=f"知识检索失败：{exc}",
        ) from exc
    return {
        "data": result,
        "meta": {"request_id": get_request_id()},
    }


@app.get("/api/knowledge/status")
def api_knowledge_status() -> dict[str, Any]:
    """Return the persisted index manifest."""
    try:
        status = get_knowledge_pipeline().status()
    except Exception as exc:
        logger.exception(
            "knowledge_index_status_failed",
            extra={"event": "knowledge_index_status_failed"},
        )
        raise HTTPException(
            status_code=503,
            detail=f"知识索引不可用：{exc}",
        ) from exc
    return {
        "data": status,
        "meta": {"request_id": get_request_id()},
    }


@app.get("/api/llm-stats")
def api_llm_stats() -> dict[str, Any]:
    return {
        "data": get_llm_call_stats(),
        "meta": {"request_id": get_request_id()},
    }


@app.get(
    "/knowledge/chunk/{chunk_id}",
    response_class=HTMLResponse,
)
def knowledge_chunk_page(
    request: Request,
    chunk_id: str,
) -> HTMLResponse:
    try:
        chunk = get_knowledge_pipeline().get_chunk(chunk_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"知识索引不可用：{exc}",
        ) from exc
    if chunk is None:
        raise HTTPException(
            status_code=404,
            detail=f"未找到知识片段：{chunk_id}",
        )
    return templates.TemplateResponse(
        request=request,
        name="knowledge_chunk.html",
        context={
            "request": request,
            "chunk": chunk,
        },
    )


def _database_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S")


@app.get("/api/production/records")
def api_production_records(
    equipment_id: str | None = Query(default=None),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    sort_by: Literal[
        "production_time",
        "batch_id",
        "equipment_id",
        "temperature_c",
        "pressure_kpa",
        "yield_pct",
    ] = Query(default="production_time"),
    order: Literal["asc", "desc"] = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    """Paginated production records with whitelisted sort and time filters."""
    if equipment_id:
        validate_equipment(equipment_id)
    if start_time and end_time and start_time > end_time:
        raise AppError(
            "INVALID_TIME_RANGE",
            "start_time 不能晚于 end_time",
            status_code=400,
        )

    result = query_production_records(
        equipment_id=equipment_id,
        start_time=_database_time(start_time),
        end_time=_database_time(end_time),
        sort_by=sort_by,
        order=order,
        page=page,
        page_size=page_size,
    )
    return {
        "data": result,
        "meta": {
            "request_id": get_request_id(),
        },
    }


def _equipment_analysis_summary(equipment_id: str) -> dict[str, Any]:
    """组装设备列表接口使用的评分、风险和统计信息。"""
    analysis = build_equipment_analysis(equipment_id)
    score_breakdown = build_health_score_breakdown(
        analysis["anomalies"]
    )

    return {
        "equipment": equipment_id,
        "health_score": score_breakdown["final_score"],
        "risk_level": risk_level_from_score(
            score_breakdown["final_score"]
        ),
        "stats": analysis["stats"],
        "score_breakdown": score_breakdown,
    }


@app.get("/api/equipment")
def api_equipment() -> dict[str, Any]:
    """返回数据源中的全部设备及当前分析摘要。"""
    items = [
        _equipment_analysis_summary(equipment_id)
        for equipment_id in get_available_equipment()
    ]
    return {
        "count": len(items),
        "items": items,
    }


@app.get("/api/equipment/{equipment_id}/analysis")
def api_equipment_analysis(equipment_id: str) -> dict[str, Any]:
    """供外部系统读取单台设备的统计、评分和异常事件。"""
    validate_equipment(equipment_id)
    analysis = build_equipment_analysis(equipment_id)
    score_breakdown = build_health_score_breakdown(
        analysis["anomalies"]
    )
    score = score_breakdown["final_score"]

    return {
        "equipment": equipment_id,
        "health_score": score,
        "risk_level": risk_level_from_score(score),
        "stats": analysis["stats"],
        "anomalies": analysis["anomalies"],
        "score_breakdown": score_breakdown,
    }


@app.get("/health/{equipment_id}")
def equipment_health(equipment_id: str) -> dict[str, Any]:
    validate_equipment(equipment_id)

    analysis = build_equipment_analysis(equipment_id)
    score_breakdown = build_health_score_breakdown(
        analysis["anomalies"]
    )
    score = score_breakdown["final_score"]

    return {
        "equipment": equipment_id,
        "health_score": score,
        "risk_level": risk_level_from_score(score),
        "stats": analysis["stats"],
        "score_breakdown": score_breakdown,
    }


def _run_diagnosis(
    equipment_id: str,
    *,
    persist: bool,
) -> dict[str, Any]:
    validate_equipment(equipment_id)

    analysis = build_equipment_analysis(equipment_id)
    score_breakdown = build_health_score_breakdown(
        analysis["anomalies"]
    )
    score = score_breakdown["final_score"]
    risk_level = risk_level_from_score(score)

    try:
        report_result = llm_reporter.generate_report_result(equipment_id)
    except Exception as exc:
        logger.exception(
            "diagnosis_report_generation_failed",
            extra={
                "event": "diagnosis_report_generation_failed",
                "equipment": equipment_id,
            },
        )
        raise HTTPException(
            status_code=503,
            detail=f"AI 报告生成失败：{exc}",
        ) from exc

    if persist:
        save_diagnosis(
            equipment_id,
            score,
            risk_level,
            report_result["report"],
            report_result["references"],
            report_result["report_json"],
            report_result["provider"],
            report_result["fallback"],
        )

    return {
        "equipment": equipment_id,
        "health_score": score,
        "risk_level": risk_level,
        "score_breakdown": score_breakdown,
        "report": report_result["report"],
        "report_json": report_result["report_json"],
        "references": report_result["references"],
        "retrieval": report_result["retrieval"],
        "provider": report_result["provider"],
        "fallback": report_result["fallback"],
        "persisted": persist,
        "latency_ms": report_result["latency_ms"],
        "prompt_tokens": report_result["prompt_tokens"],
        "completion_tokens": report_result["completion_tokens"],
    }


@app.get("/diagnose/{equipment_id}")
def diagnose_preview(equipment_id: str) -> dict[str, Any]:
    """Generate a diagnosis without writing history (safe, idempotent GET)."""
    return _run_diagnosis(equipment_id, persist=False)


@app.post("/diagnose/{equipment_id}")
def diagnose_and_record(equipment_id: str) -> dict[str, Any]:
    """Generate a diagnosis and persist it to the history table."""
    return _run_diagnosis(equipment_id, persist=True)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    equipment_id: str | None = Query(default=None),
) -> HTMLResponse:
    selected_equipment = resolve_equipment_id(equipment_id)
    validate_equipment(selected_equipment)

    analysis = build_equipment_analysis(selected_equipment)
    anomalies = analysis["anomalies"]
    stats = analysis["stats"]
    score_breakdown = build_health_score_breakdown(anomalies)
    current_score = score_breakdown["final_score"]
    current_risk = risk_level_from_score(current_score)

    data = {
        "equipment": selected_equipment,
        "health_score": current_score,
        "risk_level": current_risk,
        "abnormal_events": anomalies,
        "score_breakdown": score_breakdown,
    }

    records = get_diagnosis_records(selected_equipment)
    series = get_trend_series(
        selected_equipment,
        current_score,
        analysis=analysis,
    )

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "request": request,
            "data": data,
            "stats": stats,
            "records": records,
            "equipment_list": get_available_equipment(),
            "selected_equipment": selected_equipment,
            "history_scores": series["scores"],
            "history_times": series["days"],
            "history_count": series["history_count"],
            "trend": series["trend"],
            "score_breakdown": score_breakdown,
            "source_info": get_source_info(),
            "data_quality": validate_production_file().as_dict(),
        },
    )


@app.get("/history", response_class=HTMLResponse)
def history_page(
    request: Request,
    equipment_id: str | None = Query(default=None),
) -> HTMLResponse:
    selected_equipment = resolve_equipment_id(equipment_id)
    validate_equipment(selected_equipment)

    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "request": request,
            "records": get_diagnosis_records(selected_equipment),
            "equipment_list": get_available_equipment(),
            "selected_equipment": selected_equipment,
        },
    )


@app.get(
    "/diagnosis_detail/{record_id}",
    response_class=HTMLResponse,
)
def diagnosis_detail(
    request: Request,
    record_id: int,
) -> HTMLResponse:
    detail = get_diagnosis_detail(record_id)

    if detail is None:
        raise HTTPException(
            status_code=404,
            detail="未找到该诊断记录",
        )

    return templates.TemplateResponse(
        request=request,
        name="diagnosis_detail.html",
        context={
            "request": request,
            "detail": detail,
            "report": detail["report_text"],
            "references": detail.get("references", []),
            "structured_report": detail.get("report_json"),
            "provider": detail.get("provider"),
            "fallback": detail.get("fallback", False),
        },
    )
