import sqlite3
from datetime import datetime


# 连接数据库
conn = sqlite3.connect(
    "diagnosis_history.db"
)

cursor = conn.cursor()


# 模拟历史健康评分
history_scores = [
    82,
    75,
    68,
    55,
    45
]


for score in history_scores:

    cursor.execute(
        """
        INSERT INTO diagnosis_history
        (
            equipment,
            health_score,
            risk_level,
            report_text,
            create_time
        )

        VALUES
        (?,?,?,?,?)
        """,

        (
            "ETCH-02",
            score,
            "高风险",
            "模拟历史趋势数据",
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )
    )


conn.commit()

conn.close()


print("历史数据插入完成")