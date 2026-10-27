import sqlite3
from pathlib import Path

import pandas as pd

from anomaly_analysis import (
    PRESSURE_LIMIT,
    TEMPERATURE_LIMIT,
    YIELD_LIMIT,
)
from database_manager import ensure_production_data_current



# ==================================
# 1. 路径设置
# ==================================


BASE_DIR = Path(__file__).resolve().parent


DB_FILE = (
    BASE_DIR
    / "database"
    / "production.db"
)


OUTPUT_FILE = (
    BASE_DIR
    / "output"
    / "production_analysis_report.xlsx"
)



# ==================================
# 2. 读取数据库
# ==================================


def load_data():

    """
    从SQLite读取生产数据
    返回DataFrame
    """


    ensure_production_data_current()
    conn = sqlite3.connect(DB_FILE)


    sql = """

    SELECT *

    FROM wafer_production

    """


    df = pd.read_sql(
        sql,
        conn
    )


    conn.close()


    return df



# ==================================
# 3. 设备统计
# ==================================


def equipment_summary(df):


    summary = (

        df

        .groupby("equipment_id")

        [

            [

            "temperature_c",

            "pressure_kpa",

            "yield_pct"

            ]

        ]

        .mean()

        .round(2)

    )


    return summary



# ==================================
# 4. 异常记录
# ==================================


def anomaly_records(df):


    anomalies = df[

        (df["temperature_c"] > TEMPERATURE_LIMIT)

        |

        (df["pressure_kpa"] > PRESSURE_LIMIT)

        |

        (df["yield_pct"] < YIELD_LIMIT)

    ]


    return anomalies



# ==================================
# 5. 异常设备排名
# ==================================


def anomaly_equipment_rank(anomalies):


    result = (

        anomalies

        .groupby("equipment_id")

        .size()

        .reset_index(name="anomaly_count")
        #把索引变回普通列
        .sort_values(
            "anomaly_count",
            ascending=False
        )

    )


    return result



# ==================================
# 6. 生成Excel报告
# ==================================


def generate_excel_report():


    # 获取数据

    df = load_data()



    # 分析

    summary = equipment_summary(df)

    anomalies = anomaly_records(df)

    rank = anomaly_equipment_rank(anomalies)



    # 创建Excel

    with pd.ExcelWriter(   #ExcelWriter Excel文件编辑器
        OUTPUT_FILE,       #需要三个Sheet
        engine="openpyxl"
    ) as writer:



        # Sheet1

        summary.to_excel(

            writer,

            sheet_name="设备统计"

        )



        # Sheet2

        anomalies.to_excel(

            writer,

            sheet_name="异常记录",

            index=False

        )



        # Sheet3

        rank.to_excel(

            writer,

            sheet_name="异常设备排名",

            index=False

        )


    print(
        "Excel报告生成成功！"
    )

    print(
        OUTPUT_FILE
    )



# ==================================
# 7. 主程序
# ==================================


if __name__ == "__main__":


    generate_excel_report()
