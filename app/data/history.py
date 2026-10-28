
import json
import sqlite3
from datetime import datetime
from contextlib import closing

from app.config import settings
from app.observability import get_logger


BASE_DIR = settings.project_root
DB_NAME = settings.diagnosis_db
logger = get_logger(__name__)

VALID_RISK_LEVELS = ("正常", "关注", "高风险")


def get_connection():
    """创建数据库连接。"""
    return sqlite3.connect(DB_NAME)


def init_database():
    """初始化诊断历史数据库。"""
    with closing(get_connection()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS diagnosis_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment TEXT,
                health_score INTEGER,
                risk_level TEXT,
                report_text TEXT,
                references_json TEXT,
                report_json TEXT,
                provider TEXT,
                fallback INTEGER,
                create_time TEXT
            )
        """)
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(diagnosis_history)"
            )
        }
        if "references_json" not in columns:
            conn.execute(
                "ALTER TABLE diagnosis_history "
                "ADD COLUMN references_json TEXT"
            )
        if "report_json" not in columns:
            conn.execute(
                "ALTER TABLE diagnosis_history "
                "ADD COLUMN report_json TEXT"
            )
        if "provider" not in columns:
            conn.execute(
                "ALTER TABLE diagnosis_history "
                "ADD COLUMN provider TEXT"
            )
        if "fallback" not in columns:
            conn.execute(
                "ALTER TABLE diagnosis_history "
                "ADD COLUMN fallback INTEGER"
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_call_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                create_time TEXT NOT NULL,
                equipment TEXT NOT NULL,
                provider TEXT NOT NULL,
                success INTEGER NOT NULL,
                fallback INTEGER NOT NULL,
                latency_ms REAL NOT NULL,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                validation_error TEXT
            )
            """
        )
        conn.commit()


def save_diagnosis(
    equipment,
    health_score,
    risk_level,
    report_text,
    references=None,
    report_json=None,
    provider=None,
    fallback=False,
):
    """保存有效诊断记录，跳过无效评分和重复记录。"""

    # 第一层防护：设备编号不能为空
    if not isinstance(equipment, str) or not equipment.strip():
        logger.warning(
            "diagnosis_rejected",
            extra={
                "event": "diagnosis_rejected",
                "reason": "empty_equipment",
            },
        )
        return

    # 第二层防护：评分必须是 0～100 的有效数值
    # bool 是 int 的子类，因此这里明确排除 True / False
    if (
        isinstance(health_score, bool)
        or not isinstance(health_score, (int, float))
        or not 0 <= health_score <= 100
    ):
        logger.warning(
            "diagnosis_rejected",
            extra={
                "event": "diagnosis_rejected",
                "equipment": equipment,
                "health_score": health_score,
                "reason": "invalid_score",
            },
        )
        return

    # 第三层防护：风险等级必须合法
    if risk_level not in VALID_RISK_LEVELS:
        logger.warning(
            "diagnosis_rejected",
            extra={
                "event": "diagnosis_rejected",
                "equipment": equipment,
                "risk_level": risk_level,
                "reason": "invalid_risk_level",
            },
        )
        return

    health_score = int(health_score)

    with closing(get_connection()) as conn:
        cursor = conn.cursor()

        # 检查最近一条有效记录，避免重复保存相同评分和风险等级
        cursor.execute("""
            SELECT health_score, risk_level
            FROM diagnosis_history
            WHERE equipment = ?
              AND health_score IS NOT NULL
              AND risk_level IS NOT NULL
            ORDER BY create_time DESC, id DESC
            LIMIT 1
        """, (equipment,))

        last_record = cursor.fetchone()

        if last_record:
            last_score, last_risk = last_record

            if last_score == health_score and last_risk == risk_level:
                logger.info(
                    "diagnosis_deduplicated",
                    extra={
                        "event": "diagnosis_deduplicated",
                        "equipment": equipment,
                        "health_score": health_score,
                    },
                )
                return

        cursor.execute("""
            INSERT INTO diagnosis_history
            (
                equipment, health_score, risk_level,
                report_text, references_json, report_json,
                provider, fallback, create_time
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            equipment,
            health_score,
            risk_level,
            report_text,
            json.dumps(references or [], ensure_ascii=False),
            (
                json.dumps(report_json, ensure_ascii=False)
                if report_json is not None
                else None
            ),
            provider,
            int(fallback),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        conn.commit()
        logger.info(
            "diagnosis_saved",
            extra={
                "event": "diagnosis_saved",
                "equipment": equipment,
                "health_score": health_score,
                "risk_level": risk_level,
            },
        )


def get_health_history(equipment):
    """获取最近 5 条有效健康评分，按时间从旧到新排列。"""

    with closing(get_connection()) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, health_score, create_time
            FROM diagnosis_history
            WHERE equipment = ?
              AND health_score IS NOT NULL
              AND health_score BETWEEN 0 AND 100
              AND risk_level IN ('正常', '关注', '高风险')
            ORDER BY create_time DESC, id DESC
            LIMIT 5
        """, (equipment,))

        rows = cursor.fetchall()

    # 查询时倒序取最近 5 条，这里重新按时间正序返回
    rows.reverse()

    return [(row[1], row[2]) for row in rows]


def get_diagnosis_records(equipment_id):
    """获取指定设备的有效诊断记录列表。"""

    with closing(get_connection()) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, equipment, health_score, risk_level, create_time
            FROM diagnosis_history
            WHERE equipment = ?
              AND health_score IS NOT NULL
              AND health_score BETWEEN 0 AND 100
              AND risk_level IN ('正常', '关注', '高风险')
            ORDER BY create_time DESC, id DESC
        """, (equipment_id,))

        rows = cursor.fetchall()

    records = []

    for row in rows:
        records.append({
            "id": row[0],
            "equipment": row[1],
            "score": row[2],
            "risk": row[3],
            "time": row[4]
        })

    return records


def get_diagnosis_detail(record_id):
    """根据记录 ID 获取诊断详情。"""

    with closing(get_connection()) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT equipment, health_score, risk_level,
                   report_text, create_time, references_json,
                   report_json, provider, fallback
            FROM diagnosis_history
            WHERE id = ?
        """, (record_id,))

        row = cursor.fetchone()

    if row:
        try:
            references = json.loads(row[5]) if row[5] else []
        except json.JSONDecodeError:
            references = []
            logger.warning(
                "diagnosis_references_invalid",
                extra={
                    "event": "diagnosis_references_invalid",
                    "record_id": record_id,
                },
            )
        try:
            report_json = json.loads(row[6]) if row[6] else None
        except json.JSONDecodeError:
            report_json = None
        return {
            "equipment": row[0],
            "health_score": row[1],
            "risk_level": row[2],
            "report_text": row[3],
            "time": row[4],
            "references": references,
            "report_json": report_json,
            "provider": row[7],
            "fallback": bool(row[8]),
        }

    return None


def record_llm_call(
    equipment: str,
    provider: str,
    success: bool,
    fallback: bool,
    latency_ms: float,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    validation_error: str | None = None,
) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            """
            INSERT INTO llm_call_stats (
                create_time, equipment, provider, success, fallback,
                latency_ms, prompt_tokens, completion_tokens,
                validation_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                equipment,
                provider,
                int(success),
                int(fallback),
                float(latency_ms),
                prompt_tokens,
                completion_tokens,
                validation_error,
            ),
        )
        conn.commit()


def get_llm_call_stats() -> dict[str, object]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT provider, success, fallback, latency_ms,
                   prompt_tokens, completion_tokens, create_time
            FROM llm_call_stats
            ORDER BY id
            """
        ).fetchall()

    if not rows:
        return {
            "attempts": 0,
            "successes": 0,
            "fallbacks": 0,
            "success_rate": 0.0,
            "fallback_rate": 0.0,
            "latency_p50_ms": 0.0,
            "latency_p95_ms": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost": 0.0,
            "providers": {},
            "last_called_at": None,
        }

    latencies = sorted(float(row[3]) for row in rows)
    p95_index = round((len(latencies) - 1) * 0.95)
    prompt_tokens = sum(int(row[4] or 0) for row in rows)
    completion_tokens = sum(int(row[5] or 0) for row in rows)
    providers: dict[str, int] = {}
    for row in rows:
        providers[row[0]] = providers.get(row[0], 0) + 1

    estimated_cost = (
        prompt_tokens
        / 1_000_000
        * settings.llm_input_cost_per_million
        + completion_tokens
        / 1_000_000
        * settings.llm_output_cost_per_million
    )
    attempts = len(rows)
    successes = sum(int(row[1]) for row in rows)
    fallbacks = sum(int(row[2]) for row in rows)
    return {
        "attempts": attempts,
        "successes": successes,
        "fallbacks": fallbacks,
        "success_rate": round(successes / attempts, 4),
        "fallback_rate": round(fallbacks / attempts, 4),
        "latency_p50_ms": round(
            latencies[(len(latencies) - 1) // 2],
            3,
        ),
        "latency_p95_ms": round(latencies[p95_index], 3),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated_cost": round(estimated_cost, 6),
        "providers": providers,
        "last_called_at": rows[-1][6],
    }


if __name__ == "__main__":
    init_database()
    logger.info(
        "diagnosis_database_initialized",
        extra={
            "event": "diagnosis_database_initialized",
            "database_path": str(DB_NAME),
        },
    )
