import sqlite3


conn = sqlite3.connect(
    "diagnosis_history.db"
)

cursor = conn.cursor()


cursor.execute(
    """
    ALTER TABLE diagnosis_history
    ADD COLUMN report TEXT
    """
)


conn.commit()

conn.close()


print("数据库升级完成")