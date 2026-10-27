from app.analysis.anomalies import analyze_equipment
from app.analysis.health import (
    calculate_health_score,
    risk_level_from_score,
)



def generate_report(equipment_id):


    """
    生成设备诊断报告
    """


    anomalies = analyze_equipment(
        equipment_id
    )


    health_score = calculate_health_score(
        equipment_id
    )



    level = risk_level_from_score(health_score)



    report = f"""

================================
半导体设备健康诊断报告
================================


设备编号：
{equipment_id}


健康评分：
{health_score} / 100


风险等级：
{level}



异常事件：

"""


    for item in anomalies:


        report += f"""

批次：
{item['batch_id']}

异常类型：
{item['type']}

异常值：
{item['value']}

----------------

"""



    report += """

分析说明：

以上结果基于模拟生产数据，
通过规则检测生成。

异常不代表设备损坏，
需要结合设备报警、
维护记录和工艺参数进一步确认。


"""


    return report



if __name__ == "__main__":


    result = generate_report(
        "ETCH-02"
    )


    print(result)
