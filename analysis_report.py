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
# 1. 设置数据库路径
# ==================================


BASE_DIR = Path(__file__).resolve().parent


DB_FILE = (
    BASE_DIR
    / "database"
    / "production.db"
)



# ==================================
# 2. 从数据库读取生产数据
# ==================================


def load_data():

    """
    从SQLite读取生产数据
    返回Pandas DataFrame
    """


    ensure_production_data_current()

    # 创建数据库连接
    conn = sqlite3.connect(DB_FILE)



    # SQL查询

    sql = """

    SELECT *

    FROM wafer_production

    """



    # Pandas直接读取SQL结果

    df = pd.read_sql(
        sql,
        conn
    )



    # 关闭连接

    conn.close()



    return df



# ==================================
# 3. 设备统计分析
# ==================================


def equipment_analysis(df):

    """
    按设备统计平均指标
    """


    summary = (

        df

        .groupby("equipment_id")   # 举例： 找到所有ETCH-01 计算平均值

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
# 4. 异常批次分析
# ==================================


def anomaly_analysis(df):


    anomalies = df[

        (df["temperature_c"] > TEMPERATURE_LIMIT)

        |

        (df["pressure_kpa"] > PRESSURE_LIMIT)

        |

        (df["yield_pct"] < YIELD_LIMIT)

    ]


    return anomalies



#==================================
# 5.  统计异常设备数量
#==================================



def anomaly_equipment_analysis(anomalies):

    """
    统计异常设备数量
    """


    result = (

        anomalies

        .groupby("equipment_id")

        .size()  # 统计数量

        .sort_values(  # 降序排序
            ascending=False
        )

    )


    return result



# ==================================
# 5. 输出报告
# ==================================


def main():


    # 读取数据库

    df = load_data()



    print(
        "\n==========数据读取完成=========="
    )


    print(
        f"生产记录数量：{len(df)}"
    )



    # 设备分析

    summary = equipment_analysis(df)


    print(

        "\n==========设备统计=========="

    )


    print(summary)



    # 异常分析

    anomalies = anomaly_analysis(df)


    print(

        "\n==========异常记录=========="

    )


    print(anomalies)


    # 异常设备统计

    anomaly_count = anomaly_equipment_analysis(anomalies)


    print(
        "\n==========异常设备统计=========="
    )


    print(anomaly_count)



if __name__ == "__main__":

    main()
