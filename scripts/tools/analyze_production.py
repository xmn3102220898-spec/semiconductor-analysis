
"""Production data CLI with an explicit demo-data generator."""

import argparse
import random

import pandas as pd

from app.analysis.anomalies import (
    PRESSURE_LIMIT,
    TEMPERATURE_LIMIT,
    YIELD_LIMIT,
)
from app.config import settings
from app.data.source import load_production_records


# ==========================
# 1. 设置项目目录
# ==========================

BASE_DIR = settings.project_root
#__file__：当前 Python 文件的位置。
#.resolve().parent：取得当前文件所在的目录。

DATA_DIR = settings.data_file.parent
#/ "data"：拼接出 data 子目录的路径
OUTPUT_DIR = settings.output_dir

# 如果文件夹不存在，就自动创建
DATA_DIR.mkdir(exist_ok=True)
#mkdir(exist_ok=True)：目录不存在时创建，存在时也不会因为重复创建而报错。
OUTPUT_DIR.mkdir(exist_ok=True)

DATA_FILE = settings.data_file


# ==========================
# 2. 定义模拟数据生成函数
# ==========================

def generate_production_data():
    """生成模拟的半导体生产数据。"""

    random.seed(42)  # 固定随机种子，方便重复测试

    records = []  #多条生产记录组成的字典列表

    equipment_list = ["ETCH-01", "ETCH-02", "ETCH-03"]
    process_list = ["Etching", "Deposition"]

    for i in range(1, 31): #循环生成30条数据
        equipment = random.choice(equipment_list)  #随机生成设备
        process = random.choice(process_list)

        # 生成正常范围附近的模拟温度和压力
        temperature = round(random.uniform(70, 90), 2)
        pressure = round(random.uniform(90, 110), 2)
        yield_pct = round(random.uniform(90, 99), 2)

        # 人为设置几条异常数据，用来验证程序能否识别异常
        if i == 5:
            temperature = 120.0

        if i == 12:
            pressure = 130.0

        if i == 20:
            yield_pct = 75.0

        records.append({   #列表字典
            "batch_id": f"BATCH-{i:03d}",
            "equipment_id": equipment,
            "process": process,
            "temperature_c": temperature,
            "pressure_kpa": pressure,
            "yield_pct": yield_pct
        })

    # 将 Python 字典列表转换为 CSV 文件
    df = pd.DataFrame(records) #把列表转换成表格  
    df.to_csv(DATA_FILE, index=False, encoding="utf-8-sig")
      #to_csv()  把表格保存为 CSV
    print(f"模拟生产数据已生成：{DATA_FILE}")
    print(f"共生成 {len(df)} 条生产记录。")


# ==========================
# 3. 读取生产数据
# ==========================

def load_production_data():
    """从外部 CSV/JSON 读取生产数据。"""
    return pd.DataFrame(load_production_records())


# ==========================
# 4. 统计生产指标
# ==========================

def analyze_production_data(df):
    """计算总体统计指标和设备平均良率。"""

    print("\n========== 生产数据概览 ==========")
    print(df.head())  # 查看前 5 条记录

    print("\n========== 数据基本信息 ==========")
    print(f"生产记录总数：{len(df)}")
    print(f"涉及设备数量：{df['equipment_id'].nunique()}")  #.nunique()：计算不同设备的数量。
    print(f"平均温度：{df['temperature_c'].mean():.2f} ℃") #.mean()：计算平均值
    print(f"平均压力：{df['pressure_kpa'].mean():.2f} kPa")
    print(f"平均良率：{df['yield_pct'].mean():.2f}%")

    # 按设备分组，计算每台设备的平均良率
    equipment_summary = (
        df.groupby("equipment_id")["yield_pct"] #按设备分组。选出良率列
        .mean()
        .round(2)  #保留两位小数。
        .reset_index()  #把分组结果重新整理成普通表格
    )

    print("\n========== 各设备平均良率 ==========")
    print(equipment_summary)

    # 保存统计结果，便于后续用 Excel 查看
    summary_file = OUTPUT_DIR / "equipment_summary.csv"
    equipment_summary.to_csv(
        summary_file,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"\n设备统计结果已保存：{summary_file}")


# ==========================
# 5. 识别异常生产记录
# ==========================

def detect_anomalies(df):
    """根据演示阈值识别温度、压力和良率异常。"""

    result = df.copy()

    # 初始化异常原因列，默认每条记录都没有异常
    result["anomaly_reason"] = ""

    # 以下阈值仅为本项目模拟规则，不是行业标准
    high_temperature = result["temperature_c"] > TEMPERATURE_LIMIT
    high_pressure = result["pressure_kpa"] > PRESSURE_LIMIT
    low_yield = result["yield_pct"] < YIELD_LIMIT

    # 将各项异常原因组合起来
    result.loc[high_temperature, "anomaly_reason"] += "温度过高;"
    result.loc[high_pressure, "anomaly_reason"] += "压力过高;"
    result.loc[low_yield, "anomaly_reason"] += "良率过低;"

    # 只保留存在异常原因的记录
    anomalies = result[result["anomaly_reason"] != ""].copy()

    print("\n========== 异常识别结果 ==========")

    if anomalies.empty:
        print("没有发现符合当前规则的异常记录。")
    else:
        print(anomalies[
            [
                "batch_id",
                "equipment_id",
                "process",
                "temperature_c",
                "pressure_kpa",
                "yield_pct",
                "anomaly_reason"
            ]
        ].to_string(index=False))

    # 将异常记录保存到独立文件
    anomaly_file = OUTPUT_DIR / "anomaly_records.csv"

    anomalies.to_csv(
        anomaly_file,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"\n异常记录已保存：{anomaly_file}")
    print(f"共发现 {len(anomalies)} 条异常记录。")


# ==========================
# 6. 主程序入口
# ==========================

def main():
    """负责串联整个数据分析流程。"""

    df = load_production_data()

    analyze_production_data(df)

    detect_anomalies(df)

    print("\n数据分析任务完成！")


def cli() -> None:
    """Parse CLI arguments and run the selected operation."""
    parser = argparse.ArgumentParser(description="生产数据分析工具")
    parser.add_argument(
        "--generate",
        action="store_true",
        help="明确要求时才重新生成演示 CSV 数据",
    )
    args = parser.parse_args()

    if args.generate:
        generate_production_data()
    else:
        main()


if __name__ == "__main__":
    cli()
