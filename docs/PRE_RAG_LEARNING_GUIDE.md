# 12 周学习路线：完成到 RAG 接入之前

## 1. 这一阶段的边界

当前项目的定位是“半导体设备生产数据分析与异常识别演示系统”，使用
模拟生产数据。它可以证明你掌握了数据处理、SQL、API 和工程化方法，
不能表述为真实晶圆厂项目经验。

本阶段完成后，你应该能独立完成下面这条链路：

```text
CSV/JSON
  -> 字段校验
  -> SQLite 查询缓存
  -> SQL / Pandas 分析
  -> 异常规则与健康评分
  -> FastAPI 接口
  -> 仪表盘
  -> 自动化测试
```

RAG 从第 7 周开始。第 1～6 周的目标不是“把所有知识学完”，而是能读懂、
运行、修改并解释当前项目。

## 2. 12 周路线映射

| 周次 | 学习主题 | 项目任务 | 验收结果 |
|---|---|---|---|
| 第 1 周 | Python 数据结构、文件、异常处理 | 阅读 `production_source.py` | 能解释 CSV/JSON 如何转成统一字典 |
| 第 2 周 | SQL、表、聚合、JOIN/CTE | 运行 `sql_practice.py` | 能写出设备和异常统计 SQL |
| 第 3 周 | Pandas、分组、缺失值、描述统计 | 运行 `main.py` | 能解释 `groupby` 和异常筛选 |
| 第 4 周 | HTTP、FastAPI、请求校验、JSON | 调用新增的 `/api/*` 接口 | 能用 `/docs` 测试接口 |
| 第 5 周 | SQLite、事务、数据质量、测试 | 修改一份外部 CSV | 文件变化后页面自动更新，测试通过 |
| 第 6 周 | 半导体业务、MES、SPC、Git、Linux | 完成发布前检查 | 能在 Linux 命令下启动并解释项目边界 |
| 第 7～10 周 | 文本切分、Embedding、向量检索、Prompt 增强 | 进入 RAG 开发 | 暂不在本阶段实现 |
| 第 11 周 | RAG 效果评估与错误分析 | 建立问题集和命中率指标 | 暂不在本阶段实现 |
| 第 12 周 | 项目包装、简历、面试 | 整理演示和项目讲述 | 暂不在本阶段完成 |

## 3. 运行基线

在项目目录执行：

```powershell
python -m pip install -r requirements.txt
python -X utf8 -m unittest discover -s tests -v
python -X utf8 main.py
python -X utf8 sql_practice.py
python -m uvicorn main_api:app --reload
```

浏览器打开：

```text
http://127.0.0.1:8000/dashboard
http://127.0.0.1:8000/docs
```

Linux 环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn main_api:app --host 0.0.0.0 --port 8000
```

## 4. 第 1 周：Python 与外部数据

### 阅读顺序

1. `production_source.py`
2. `database_manager.py`
3. `database_query.py`

重点看四个动作：

- `resolve_data_file()`：把相对路径转换成项目内的绝对路径。
- `_map_record()`：把 CSV 行或 JSON 对象转换成固定字段。
- `sync_production_data()`：文件变化时更新 SQLite。
- `execute_query()`：统一执行 SQL 并返回元组列表。

### 实际操作

打开 `data/production_data.csv`，把一条记录的良率改成 `80`，保存后刷新
仪表盘。你应该看到异常事件数和健康评分发生变化。

练习后请改回原值。也可以复制一份文件，通过环境变量测试：

```powershell
$env:PRODUCTION_DATA_FILE = "data/your_production.csv"
python -m uvicorn main_api:app --reload
```

### 验收问题

- 为什么数据库只是“查询缓存”，外部文件才是当前数据源？
- 为什么批次编号必须唯一？
- 如果字段缺失，错误应该在写数据库之前还是之后发现？

### 常见错误

| 错误 | 原因 | 排查 |
|---|---|---|
| `ProductionDataError` | 文件不存在、字段缺失或数值非法 | 按报错行号检查 CSV/JSON |
| 中文乱码 | 编辑器或终端编码不一致 | 文件使用 UTF-8，Python 加 `-X utf8` |
| 修改文件后数据没变 | 应用读取了另一条路径 | 检查 `PRODUCTION_DATA_FILE` 和页面数据源 |

## 5. 第 2 周：SQL 与 SQLite

### 实际操作

运行：

```powershell
python -X utf8 sql_practice.py
```

重点理解：

- `GROUP BY`：先按设备或工艺分组，再做聚合。
- `AVG/COUNT/ROUND`：计算平均值、数量和显示精度。
- `UNION ALL`：把温度、压力、良率三类异常统一成事件明细。
- `WITH`：先用公共表表达式整理中间结果，再做统计。

### 自己增加一个查询

在 `sql_practice.py` 的 `QUERIES` 中增加“每个工艺的平均温度”，然后运行
脚本验证。参考 SQL：

```sql
SELECT
    process,
    ROUND(AVG(temperature_c), 2) AS avg_temperature
FROM wafer_production
GROUP BY process
ORDER BY process;
```

### 验收问题

- `WHERE` 和 `HAVING` 分别过滤什么？
- 为什么异常事件数可能大于异常批次数？
- 如果同一批次同时温度异常和压力异常，`UNION ALL` 会产生几行？

### 常见错误

| 错误 | 原因 | 处理 |
|---|---|---|
| `no such table` | 数据库尚未初始化 | 启动应用或运行 `python database_manager.py` |
| `database is locked` | 多个进程同时写 SQLite | 停止重复启动的服务，避免并发写 |
| 聚合结果不对 | 忘记 `GROUP BY` | 非聚合字段必须出现在分组中 |

## 6. 第 3 周：Pandas 数据处理

### 实际操作

运行：

```powershell
python -X utf8 main.py
```

观察 `groupby("equipment_id")["yield_pct"].mean()` 如何把 30 条批次记录
变成三台设备的平均良率。

然后修改 `main.py`，增加按工艺统计平均温度：

```python
process_summary = (
    df.groupby("process")["temperature_c"]
      .mean()
      .round(2)
      .reset_index()
)
print(process_summary)
```

### 验收问题

- DataFrame 的列和 SQL 表的列是什么对应关系？
- 为什么布尔筛选 `df["temperature_c"] > 100` 可以筛出异常批次？
- 用 Pandas 和 SQL 得到同一统计时，如何验证结果一致？

## 7. 第 4 周：FastAPI 与 HTTP API

启动服务后打开 `http://127.0.0.1:8000/docs`，直接测试接口：

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/healthz` | 服务存活检查 |
| `GET` | `/api/data-source` | 当前数据文件和记录数 |
| `GET` | `/api/equipment` | 全部设备摘要 |
| `GET` | `/api/equipment/{id}/analysis` | 单台设备统计与异常 |
| `GET` | `/health/{id}` | 兼容的评分接口 |
| `GET` | `/health_history/{id}` | 趋势数据 |

PowerShell 调用：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/equipment |
    ConvertTo-Json -Depth 6
```

Linux 调用：

```bash
curl -s http://127.0.0.1:8000/api/equipment/ETCH-02/analysis
```

### 验收问题

- 路径参数、查询参数分别是什么？
- 200、404、503 在该项目中分别代表什么？
- `response.json()` 得到的是 Python 的什么类型？
- 为什么页面接口和 API 要共用同一套评分逻辑？

### 常见错误

| 错误 | 原因 | 处理 |
|---|---|---|
| `Address already in use` | 8000 端口被占用 | 使用 `--port 8001` |
| 404 | 设备编号不在当前数据文件 | 先调用 `/api/equipment` 查有效编号 |
| 503 | 数据文件不可用 | 查看接口返回的 `detail` |

## 8. 第 5 周：数据质量与自动化测试

运行：

```powershell
python -X utf8 -m unittest discover -s tests -v
```

测试覆盖了：

- CSV 和 JSON 读取；
- 中文表头；
- 重复批次拒绝；
- 文件变化后的数据库刷新；
- 三台设备评分和统计；
- 设备切换和 API 返回；
- 仪表盘不依赖大模型。

### 实际操作

在临时 JSON 中制造一个重复批次，观察系统是否拒绝导入。再删除一个必需
字段，确认错误发生在写库之前。

## 9. 第 6 周：半导体业务、Git 与 Linux

### 半导体概念映射

| 半导体概念 | 当前项目中的对应物 |
|---|---|
| Wafer/Lot/Batch | `batch_id` |
| Equipment/Tool | `equipment_id` |
| Process step | `process` |
| Process parameter | `temperature_c`、`pressure_kpa` |
| Quality result | `yield_pct` |
| SPC/异常监控规则 | `anomaly_analysis.py` 中的阈值 |
| MES 数据导入 | CSV/JSON 外部数据文件 |
| 设备看板 | `/dashboard` |

项目中的 `100℃`、`120kPa`、`90%` 都是演示阈值，不是行业标准。

### Git 操作

如果这是一个独立作品集仓库：

```powershell
git init
git add .
git commit -m "feat: complete pre-RAG semiconductor data platform"
git status
```

如果项目已经纳入上层仓库，不要重复执行 `git init`，只在上层仓库中检查
`git status` 并提交本项目目录。

提交前确认 `.env`、数据库和缓存没有被提交。`.env.example` 只展示变量名，
不能写入真实密钥。

### Linux 验收

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -X utf8 -m unittest discover -s tests -v
python -m uvicorn main_api:app --host 0.0.0.0 --port 8000
curl -s http://127.0.0.1:8000/healthz
```

## 10. 进入 RAG 前的验收清单

- [ ] 三台设备都能从下拉框切换，统计数字随设备变化。
- [ ] `/api/equipment/ETCH-02/analysis` 显示 3 个异常事件和 3 个异常批次。
- [ ] 健康评分 45，风险等级高风险，批次趋势为“持续下降”。
- [ ] `ETCH-01` 显示 7 个批次点、`ETCH-02` 显示 12 个点、
      `ETCH-03` 显示 11 个点。
- [ ] 修改 CSV 或 JSON 后，下一次请求自动刷新数据。
- [ ] 缺少字段、重复批次、非法良率会被拒绝。
- [ ] 15 项以上自动化测试通过。
- [ ] 能在 `/docs` 中完成一次接口调用。
- [ ] 能解释“模拟项目”和“真实工厂经验”的边界。

完成这份清单后，再开始学习文档切分、Embedding、语义检索和 RAG 评估。
