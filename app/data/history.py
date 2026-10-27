
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
                create_time TEXT
            )
        """)
        conn.commit()


def save_diagnosis(equipment, health_score, risk_level, report_text):
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
            (equipment, health_score, risk_level, report_text, create_time)
            VALUES (?, ?, ?, ?, ?)
        """, (
            equipment,
            health_score,
            risk_level,
            report_text,
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
                   report_text, create_time
            FROM diagnosis_history
            WHERE id = ?
        """, (record_id,))

        row = cursor.fetchone()

    if row:
        return {
            "equipment": row[0],
            "health_score": row[1],
            "risk_level": row[2],
            "report_text": row[3],
            "time": row[4]
        }

    return None


if __name__ == "__main__":
    init_database()
    logger.info(
        "diagnosis_database_initialized",
        extra={
            "event": "diagnosis_database_initialized",
            "database_path": str(DB_NAME),
        },
    )
