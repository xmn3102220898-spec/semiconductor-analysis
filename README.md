# 半导体设备 AI 诊断系统

## 启动

```powershell
python -m pip install -r requirements.txt
python -m uvicorn main_api:app --reload
```

打开：

- 仪表盘：`http://127.0.0.1:8000/dashboard`
- API 文档：`http://127.0.0.1:8000/docs`

Linux 启动：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn main_api:app --host 0.0.0.0 --port 8000
```

## 当前数据链路

1. 后端读取 `data/production_data.csv`（或环境变量
   `PRODUCTION_DATA_FILE` 指定的 CSV/JSON）。
2. 校验字段、数值范围和批次唯一性。
3. 文件内容变化时自动同步到 `database/production.db`。
4. 异常识别、健康评分、仪表盘统计和趋势分析使用同一套规则。
5. 趋势按外部数据中的生产批次顺序累计扣分，末点与当前评分一致。

字段说明见 [data/README.md](data/README.md)。

## 主要接口

| 接口 | 用途 |
|---|---|
| `GET /` | 跳转仪表盘 |
| `GET /healthz` | 服务存活检查 |
| `GET /api/data-source` | 当前数据文件与记录数 |
| `GET /api/equipment` | 全部设备分析摘要 |
| `GET /api/equipment/{id}/analysis` | 单台设备统计与异常事件 |
| `GET /dashboard` | 设备仪表盘，支持 `equipment_id` |
| `GET /health/{equipment_id}` | 当前健康评分和生产统计 |
| `GET /health_history/{equipment_id}` | 趋势图数据与趋势结论 |
| `GET /diagnose/{equipment_id}` | 调用大模型生成并保存诊断报告 |
| `GET /history` | 历史诊断记录 |

## 测试

```powershell
python -X utf8 -m unittest discover -s tests -v
python -X utf8 sql_practice.py
```

## 学习与项目文档

- [接入 RAG 前的 12 周学习路线](docs/PRE_RAG_LEARNING_GUIDE.md)
- [项目说明、半导体业务映射与面试表达](docs/PROJECT_AND_INTERVIEW.md)

> 生产和设备数据均为模拟数据，不代表真实晶圆厂生产经验。
