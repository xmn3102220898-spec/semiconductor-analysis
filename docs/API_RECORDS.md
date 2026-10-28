# 生产记录查询接口

## `GET /api/production/records`

该接口使用新的成功响应 envelope；原有接口继续保持兼容。

### 查询参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `equipment_id` | 全部 | 设备编号 |
| `start_time` | 无 | ISO 时间下界，包含边界 |
| `end_time` | 无 | ISO 时间上界，包含边界 |
| `sort_by` | `production_time` | 白名单排序字段 |
| `order` | `desc` | `asc` 或 `desc` |
| `page` | 1 | 从 1 开始 |
| `page_size` | 20 | 1～200 |

排序白名单：

- `production_time`
- `batch_id`
- `equipment_id`
- `temperature_c`
- `pressure_kpa`
- `yield_pct`

不允许将任意客户端字符串直接拼进 SQL。

### 示例

```text
GET /api/production/records
    ?equipment_id=ETCH-02
    &start_time=2026-09-10T00:00:00
    &end_time=2026-09-12T23:59:59
    &sort_by=production_time
    &order=asc
    &page=1
    &page_size=50
```

响应：

```json
{
  "data": {
    "items": [
      {
        "id": 10,
        "batch_id": "BATCH-010",
        "equipment_id": "ETCH-02",
        "process": "Etching",
        "temperature_c": 84.09,
        "pressure_kpa": 90.92,
        "yield_pct": 92.05,
        "production_time": "2026-09-10 08:00:00"
      }
    ],
    "pagination": {
      "page": 1,
      "page_size": 50,
      "total": 3,
      "total_pages": 1
    },
    "filters": {},
    "sort": {
      "sort_by": "production_time",
      "order": "asc"
    }
  },
  "meta": {
    "request_id": "..."
  }
}
```

非法时间范围返回 HTTP 400 和错误码 `INVALID_TIME_RANGE`。非法排序字段、
页码或分页大小由 FastAPI 返回 422。

## 索引

`wafer_production` 创建以下索引：

- `equipment_id`
- `batch_id`
- `production_time`
- `(equipment_id, production_time)`

旧数据库在启动时通过 `ALTER TABLE ... ADD COLUMN production_time TEXT`
增量迁移，不删除已有记录。

## 模拟时间说明

当前 CSV 的生产时间覆盖 2026-09-01 至 2026-09-30，完全用于演示分页和
时间过滤，不代表真实工厂生产记录。
