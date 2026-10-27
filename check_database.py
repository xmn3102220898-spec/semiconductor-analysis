import sqlite3
from pathlib import Path

db_file = (
    Path(__file__).resolve().parent
    / "database"
    / "production.db"
)

conn = sqlite3.connect(db_file)
cursor = conn.cursor()

# 查看生产表的字段
cursor.execute("PRAGMA table_info(wafer_production)")
print("数据库字段：")
for column in cursor.fetchall():
    print(column)

# 查看生产记录总数
cursor.execute("SELECT COUNT(*) FROM wafer_production")
print("\n生产记录总数：", cursor.fetchone()[0])

# 查看数据库中有哪些设备
cursor.execute("""
    SELECT equipment_id, COUNT(*)
    FROM wafer_production
    GROUP BY equipment_id
""")
print("\n各设备记录数量：")
for row in cursor.fetchall():
    print(row)

conn.close()