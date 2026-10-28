# 数据质量与分析规则

## 1. 数据源

默认数据文件为 `data/production_data.csv`，可通过
`PRODUCTION_DATA_FILE` 指向 CSV 或 JSON。分析规则独立存放于
`config/analysis_rules.json`，可通过 `ANALYSIS_RULES_FILE` 覆盖。

## 2. 缺失值与格式策略

当前策略是“拒绝整条记录”，不做自动填充：

- 必需字段缺失：拒绝。
- 文本字段为空：拒绝。
- 数值无法解析或不是有限值：拒绝。
- 设备编号不符合配置的正则：拒绝。
- 工艺类型不在允许列表：拒绝。
- 参数超出配置范围：拒绝。
- 批次编号重复：后续记录拒绝。

文件格式、JSON 语法、空文件等文件级错误不会写数据库。

## 3. 默认验证范围

| 字段 | 允许范围/规则 |
|---|---|
| `temperature_c` | -100～500 ℃ |
| `pressure_kpa` | 0～1000 kPa |
| `yield_pct` | 0～100% |
| `equipment_id` | 大写字母/数字分段，例如 `ETCH-02` |
| `process` | 配置允许列表 |

这些是模拟项目的数据质量边界，不是半导体行业标准。

## 4. 异常阈值覆盖

规则按以下优先级解析：

1. `equipment_overrides` 中指定设备编号。
2. `equipment_prefixes` 匹配的设备类型。
3. `equipment_types` 中该类型的阈值。
4. `default_thresholds`。

示例：

```json
{
  "equipment_overrides": {
    "ETCH-02": {
      "temperature_c": 99
    }
  }
}
```

只覆盖温度阈值时，压力和良率继续继承设备类型或全局阈值。

规则文件在进程内缓存；修改规则后需要重启服务，避免运行中的分析结果
在请求之间无提示切换口径。

## 5. 数据质量接口

```text
GET /api/data-quality
```

返回：

- `healthy`
- `total_records`
- `valid_records`
- `rejected_records`
- `reason_counts`
- `record_errors`，最多保留 100 条详细错误
- `details_truncated`

数据文件无效时服务仍可启动，质量接口返回 200 和明确原因；依赖生产数据的
接口返回 503，避免使用数据库中的旧数据冒充当前结果。

## 6. 扣分可解释性

`/api/equipment/{id}/analysis` 和 `/health/{id}` 返回
`score_breakdown`：

```json
{
  "base_score": 100,
  "total_penalty": 55,
  "final_score": 45,
  "floor_applied": false,
  "deductions": [
    {
      "batch_id": "BATCH-005",
      "type": "温度异常",
      "threshold": 100.0,
      "penalty": 15,
      "remaining_score": 85
    }
  ]
}
```

页面、API 和趋势使用同一份异常事件与扣分明细。
