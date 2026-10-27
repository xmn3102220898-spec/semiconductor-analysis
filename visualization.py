
import pandas as pd
import matplotlib.pyplot as plt

from app.analysis.anomalies import TEMPERATURE_LIMIT
from app.config import settings
from app.data.source import load_production_records
# matplotlib.pyplot 绘图接口，用来画柱状图和折线图

# ======================================
# 1. 设置项目目录和图表保存位置
# ======================================

# __file__ 表示当前 visualization.py 文件的位置
BASE_DIR = settings.project_root

DATA_FILE = settings.data_file
OUTPUT_DIR = settings.output_dir

# 如果 output 文件夹不存在，就自动创建
OUTPUT_DIR.mkdir(exist_ok=True)


# ======================================
# 2. 设置图表的中文字体
# ======================================

# Windows 通常有微软雅黑；如果没有，可尝试 SimHei（黑体）
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]

# 解决坐标轴负号显示成方框的问题
plt.rcParams["axes.unicode_minus"] = False


# ======================================
# 3. 读取生产数据
# ======================================

def load_data():
    """读取当前外部 CSV/JSON 生产数据文件。"""
    df = pd.DataFrame(load_production_records())

    print(f"成功读取 {len(df)} 条生产记录。")

    return df


# ======================================
# 4. 绘制设备平均良率柱状图
# ======================================

def plot_equipment_yield(df):
    """计算各设备的平均良率，并绘制柱状图。"""

    # 按设备分组，计算每台设备的平均良率
    summary = (
        df.groupby("equipment_id")["yield_pct"]
          #groupby 叫作分组统计
        .mean()
        .round(2)
        .reset_index() #把分组结果重新变回普通表格
    )

    # 创建一张新的图表，设置图像大小
    plt.figure(figsize=(8, 5))

    # x 轴是设备名称，y 轴是设备平均良率
    plt.bar(  #绘制柱状图
        summary["equipment_id"],
        summary["yield_pct"]
    )

    # 设置标题、横轴名称、纵轴名称
    plt.title("各设备平均良率对比")
    plt.xlabel("设备编号")
    plt.ylabel("平均良率（%）")

    # 将纵轴显示范围设置为 0 到 100
    plt.ylim(0, 100)  #良率用百分比表示

    # 给每根柱子标注具体的平均良率
    for i, value in enumerate(summary["yield_pct"]):
        plt.text(
            i,
            value + 1,
            f"{value:.2f}%",
            ha="center"
        )

    # 自动调整图表间距，减少文字重叠
    plt.tight_layout()

    # 保存图片；保存路径使用项目内的 output 文件夹
    chart_file = OUTPUT_DIR / "equipment_yield.png"
    plt.savefig(chart_file, dpi=150) #dpi 图片分辨率

    # 关闭当前图表，释放绘图资源
    plt.close()

    print(f"设备良率图已保存：{chart_file}")


# ======================================
# 5. 绘制生产批次温度趋势图
# ======================================

def plot_temperature_trend(df):
    """按照批次顺序绘制温度变化趋势。"""

    # 创建新的图表
    plt.figure(figsize=(12, 5))

    # x 轴使用批次编号，y 轴使用生产温度
    plt.plot(  # 绘制折线图
        df["batch_id"], # X
        df["temperature_c"],# Y
        marker="o", #在每个数据点画一个圆点
        label="生产温度"
    )

    # 添加一条演示用的温度参考线
    # 这只是本项目的练习阈值，不是行业标准
    plt.axhline(  #水平参考线
        y=TEMPERATURE_LIMIT,
        linestyle="--",
        label=f"演示异常阈值（{TEMPERATURE_LIMIT:g}℃）"
    )

    # 设置图表标题和坐标轴名称
    plt.title("各生产批次温度变化趋势")
    plt.xlabel("生产批次")
    plt.ylabel("温度（℃）")

    # 批次较多时旋转标签，避免文字重叠
    plt.xticks(rotation=60)

    # 显示图例，用来解释曲线和参考线
    plt.legend()

    # 调整布局
    plt.tight_layout()

    # 先保存图表到 PNG 文件
    chart_file = OUTPUT_DIR / "temperature_trend.png"
    plt.savefig(chart_file, dpi=150)

    # 保存完成后关闭图表
    plt.close()

    print(f"温度趋势图已保存：{chart_file}")


# ======================================
# 6. 主程序：串联整个可视化流程
# ======================================

def main():
    """读取数据，然后依次生成两张图表。"""

    df = load_data()

    plot_equipment_yield(df)

    plot_temperature_trend(df)

    print("\n可视化任务完成！")


# 直接运行本文件时，启动主程序
if __name__ == "__main__":
    main()
