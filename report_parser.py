
import re


def parse_report(report_text):
    """
    将诊断报告转换为结构化数据。

    提取：
    1. 设备编号
    2. 健康评分
    3. 风险等级
    4. 异常事件列表
    """

    result = {
        "equipment": None,
        "health_score": None,
        "risk_level": None,
        "abnormal_events": [],
    }

    if not isinstance(report_text, str) or not report_text.strip():
        return result

    # 1. 提取设备编号
    # 支持：
    # 设备编号：ETCH-02
    # | 设备编号 | ETCH-02 |
    equipment_match = re.search(
        r"设备编号\s*[:：|]?\s*\**\s*"
        r"(ETCH-\d+)\b",
        report_text,
        re.IGNORECASE,
    )

    if equipment_match:
        result["equipment"] = equipment_match.group(1).upper()

    # 2. 提取健康评分
    # 支持：
    # 健康评分：45 / 100
    # | 健康评分 | 45 / 100 |
    score_match = re.search(
        r"健康评分\s*[:：|]?\s*\**\s*"
        r"(\d{1,3})\s*(?:/\s*100)?",
        report_text,
    )

    if score_match:
        score = int(score_match.group(1))

        if 0 <= score <= 100:
            result["health_score"] = score

    # 3. 根据报告中的健康评分判断风险等级
    # 若报告没有评分，则暂不生成风险等级
    if result["health_score"] is not None:
        score = result["health_score"]

        if score < 60:
            result["risk_level"] = "高风险"
        elif score < 80:
            result["risk_level"] = "关注"
        else:
            result["risk_level"] = "正常"

    # 4. 提取异常事件
    # 支持 Markdown 表格：
    # | BATCH-001 | 温度异常 | 120℃ |
    # | BATCH-002 | 压力异常 | 130 kPa |
    # | BATCH-003 | 低良率异常 | 75% |
    #
    # 同时支持不带单位空格的数值，以及普通文本中的异常记录。
    batch_pattern = (
        r"(BATCH-[A-Za-z0-9_-]+|"
        r"[A-Za-z0-9]+-[A-Za-z0-9_-]+)"
    )

    anomaly_pattern = re.compile(
        rf"{batch_pattern}\s*\|\s*"
        r"(温度异常|压力异常|低良率异常)\s*\|\s*"
        r"([0-9]+(?:\.[0-9]+)?\s*(?:℃|°C|kPa|%))",
        re.IGNORECASE,
    )

    seen_events = set()

    for match in anomaly_pattern.finditer(report_text):
        batch = match.group(1).strip()
        anomaly_type = match.group(2).strip()
        value = re.sub(r"\s+", "", match.group(3))

        event_key = (batch, anomaly_type, value)

        # 避免同一异常记录被重复计数
        if event_key in seen_events:
            continue

        seen_events.add(event_key)

        result["abnormal_events"].append({
            "batch": batch,
            "type": anomaly_type,
            "value": value,
        })

    return result


if __name__ == "__main__":
    test_report = """
    # 设备诊断报告

    设备编号：ETCH-02

    健康评分：45 / 100

    | 批次编号 | 异常类型 | 检测数值 |
    |---|---|---|
    | BATCH-001 | 温度异常 | 120℃ |
    | BATCH-002 | 压力异常 | 130 kPa |
    | BATCH-003 | 低良率异常 | 75% |
    """

    parsed = parse_report(test_report)

    print("解析结果：")
    print(parsed)

    print("异常事件数量：", len(parsed["abnormal_events"]))
