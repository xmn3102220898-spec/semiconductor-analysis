"""半导体设备 AI 诊断系统 FastAPI 入口。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from anomaly_analysis import build_equipment_analysis
from database import (
    get_diagnosis_detail,
    get_diagnosis_records,
    init_database,
    save_diagnosis,
)
from database_manager import create_database, sync_production_data
from database_query import query_record_count
from equipment_data import get_equipment_ids
from health_score import (
    calculate_batch_health_trend,
    calculate_health_score_from_anomalies,
    risk_level_from_score,
)
from llm_report_generator import generate_report
from production_source import (
    ProductionDataError,
    summarize_source,
)
from trend_analysis import analyze_health_trend


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="半导体设备AI诊断系统",
    description="基于 Python、RAG 和 DeepSeek 的设备分析平台",
    version="1.1",
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _initialize_storage() -> None:
    create_database()
    init_database()
    sync_production_data()


try:
    _initialize_storage()
except ProductionDataError:
    # 保留应用可启动性，具体错误在访问数据接口时返回 503。
    pass


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
    score = calculate_health_score_from_anomalies(analysis["anomalies"])
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


def _equipment_analysis_summary(equipment_id: str) -> dict[str, Any]:
    """组装设备列表接口使用的评分、风险和统计信息。"""
    analysis = build_equipment_analysis(equipment_id)
    score = calculate_health_score_from_anomalies(analysis["anomalies"])

    return {
        "equipment": equipment_id,
        "health_score": score,
        "risk_level": risk_level_from_score(score),
        "stats": analysis["stats"],
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
    score = calculate_health_score_from_anomalies(analysis["anomalies"])

    return {
        "equipment": equipment_id,
        "health_score": score,
        "risk_level": risk_level_from_score(score),
        "stats": analysis["stats"],
        "anomalies": analysis["anomalies"],
    }


@app.get("/health/{equipment_id}")
def equipment_health(equipment_id: str) -> dict[str, Any]:
    validate_equipment(equipment_id)

    analysis = build_equipment_analysis(equipment_id)
    score = calculate_health_score_from_anomalies(analysis["anomalies"])

    return {
        "equipment": equipment_id,
        "health_score": score,
        "risk_level": risk_level_from_score(score),
        "stats": analysis["stats"],
    }


@app.get("/diagnose/{equipment_id}")
def diagnose_equipment(equipment_id: str) -> dict[str, Any]:
    validate_equipment(equipment_id)

    analysis = build_equipment_analysis(equipment_id)
    score = calculate_health_score_from_anomalies(analysis["anomalies"])
    risk_level = risk_level_from_score(score)

    try:
        report = generate_report(equipment_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"AI 报告生成失败：{exc}",
        ) from exc

    save_diagnosis(
        equipment_id,
        score,
        risk_level,
        report,
    )

    return {
        "equipment": equipment_id,
        "health_score": score,
        "risk_level": risk_level,
        "report": report,
    }


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
    current_score = calculate_health_score_from_anomalies(anomalies)
    current_risk = risk_level_from_score(current_score)

    data = {
        "equipment": selected_equipment,
        "health_score": current_score,
        "risk_level": current_risk,
        "abnormal_events": anomalies,
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
            "source_info": get_source_info(),
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
        },
    )
