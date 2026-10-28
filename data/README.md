# 生产数据文件

后端默认读取 `data/production_data.csv`。也可以通过环境变量切换到其他
CSV 或 JSON 文件。仓库提供了
`data/production_data.example.json` 作为格式示例：

```powershell
$env:PRODUCTION_DATA_FILE = "data/production_data.example.json"
python -m uvicorn main_api:app --reload
```

此时设备列表会从示例文件中动态生成，不会继续显示默认 CSV 中的三台设备。

## 字段

| 字段 | 含义 | 示例 |
|---|---|---|
| `batch_id` | 批次编号，必须唯一 | `BATCH-001` |
| `equipment_id` | 设备编号 | `ETCH-02` |
| `process` | 工艺类型 | `Etching` |
| `temperature_c` | 温度，单位 ℃ | `84.5` |
| `pressure_kpa` | 压力，单位 kPa | `101.2` |
| `yield_pct` | 良率，0～100 | `96.3` |
| `production_time` | 可选生产时间，ISO 日期或日期时间 | `2026-09-01 08:00:00` |

CSV 表头支持上述英文字段，也支持“批次编号、设备编号、工艺、温度、
压力、良率、生产时间”等中文表头。JSON 可以是记录数组，也可以使用
`{"records": [...]}` 结构。

`production_time` 缺失时记录仍可导入，但不会出现在有时间范围的查询结果中。

## 刷新规则

应用根据文件内容哈希判断数据是否变化。启动后会先同步一次；运行期间
修改 CSV/JSON 后，下一次查询会自动刷新 SQLite 查询缓存，无需重启服务。

字段格式、设备编号、允许工艺、数值范围和历史异常阈值见
`config/analysis_rules.json`。完整说明见
`docs/DATA_QUALITY_AND_RULES.md`。
