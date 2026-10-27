from report_parser import parse_report


text = """

设备编号 | ETCH-02

健康评分 | 45 /100


异常记录：

BATCH-005 | 温度异常 | 120.0℃

BATCH-012 | 压力异常 | 130.0kPa

BATCH-020 | 低良率异常 | 75.0%

"""


result = parse_report(text)


print(result)

print("================")

print(text)