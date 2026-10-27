# 半导设备 AI 诊断平台：P0 审计与基线

> 审计日期：2026-10-27  
> 审计范围：当前工作区代码与本地运行结果  
> 审计边界：本轮只做 P0，不修改业务代码，不进入 P1  
> 数据声明：全部生产数据、诊断和知识库内容均为模拟/学习数据，不代表真实晶圆厂经验

## 1. 结论摘要

当前项目的主数据链路可以运行，现有 23 项测试全部通过。核心问题集中在
AI/RAG 层、配置与可观测性、工程交付和根目录模块边界，而不是基础数据
查询无法使用。

原始问题清单中的核心判断大多成立，但需要纠正三点：

1. “没有接口层测试”不成立。`tests/test_data_pipeline.py` 已经使用
   `TestClient` 覆盖多个 API，但覆盖不完整。
2. “第五层成果完全看不见”不准确。`/history` 和
   `/diagnosis_detail/{id}` 可以显示已保存报告；问题在于仪表盘不展示
   诊断记录、扣分明细和检索引用。
3. `diagnosis_history.py` 实际不存在；对应逻辑主要在 `database.py`。

另外发现两个高优先级问题：

- `main_api.py:54-57` 在启动数据初始化失败时执行 `except ...: pass`，
  直接吞掉错误，违反“不可静默失败”。
- `database_query.py:23` 每次查询前都调用同步检查；该检查会先计算文件
  哈希，再完整读取和校验文件。小数据无感，但会直接破坏 10 万行数据的
  查询延迟目标。

## 2. 环境与依赖基线

### 2.1 运行环境

| 项目 | 当前值 |
|---|---|
| Python | 3.12.0 |
| 操作系统 | Windows（当前审计环境） |
| Web 框架 | FastAPI 0.143.0 |
| ASGI Server | Uvicorn 0.54.0 |
| 数据处理 | pandas 3.0.6 |
| 数值计算 | numpy 2.5.3 |
| 大模型 SDK | openai 3.26.0 |
| 向量模型 | sentence-transformers 6.1.0 |
| 深度学习运行时 | torch 2.14.1 |
| HTTP 测试客户端依赖 | httpx 0.28.1 |

### 2.2 直接依赖实际情况

代码直接使用但 `requirements.txt` 未显式声明的包：

- `numpy`：`rag_assistant.py`、`semantic_search.py`
- `matplotlib`：`visualization.py`
- `openpyxl`：`generate_report.py`
- `scikit-learn`：`embedding_test.py`
- `httpx`：FastAPI `TestClient`

`requirements.txt` 当前只有 7 个未锁版本依赖：

```text
fastapi
uvicorn[standard]
jinja2
pandas
python-dotenv
openai
sentence-transformers
```

结论：

- 当前环境能运行，不代表新环境仅按 `requirements.txt` 一定完整运行。
- 没有 dev/prod 依赖拆分。
- 没有版本锁定，无法复现当前依赖树。
- `sentence-transformers + torch` 会显著增加 Docker 镜像和安装成本，
  P1 应把基础 Web/分析依赖与 AI 可选用例分开考虑。

### 2.3 测试与静态检查工具

| 工具 | 当前状态 |
|---|---|
| `unittest` | 可用 |
| `pytest` | 未安装 |
| `coverage` | 未安装 |
| `ruff` | 未安装 |
| `mypy` | 未安装 |
| `pyflakes` | 已安装，可作为临时审计工具 |

当前仓库没有覆盖率配置、lint 配置或 CI 配置。

## 3. 可执行验证结果

### 3.1 单元与接口测试

执行命令：

```powershell
python -X utf8 -m unittest discover -s tests -v
```

实际结果摘录：

```text
Ran 23 tests in 0.819s

OK
```

测试分类：

- 数据源/同步：6 项
- 规则/评分/趋势：4 项
- 接口与页面：13 项

根目录 `test_parser.py`、`test_trend.py` 只是 print 演示脚本，没有断言，
也没有被 `-s tests` 发现。

### 3.2 编译检查

```powershell
python -m compileall -q .
```

实际结果：退出码 0，没有语法错误。

### 3.3 静态检查

```powershell
python -m pyflakes .
```

实际输出：

```text
.\data_formatter.py:38:9: local variable 'equipment' is assigned to but never used
```

### 3.4 手工接口烟雾测试

| 路径 | 状态码 |
|---|---:|
| `/health/ETCH-02` | 200 |
| `/history?equipment_id=ETCH-02` | 200 |
| `/diagnosis_detail/16` | 200 |

这些路径可运行，但没有全部进入自动化测试。

### 3.5 RAG 检索烟雾测试

使用本地缓存的向量模型，在当前机器执行 4 个问题：

- 知识库：3 个 txt，共 19 个 chunk。
- chunk 元数据只有 `source`、`content`。
- 当前 chunk 最大长度：77 个字符。
- 模型加载并建立 19×384 向量索引：约 2.303 秒。
- 单次语义检索：约 6.26～9.49 ms。

这些数字只是当前机器的一次性烟雾测试，不是 P95，也不证明检索准确率。

关键行为：

- 语义检索无条件返回 top 3，即使问题没有可靠匹配。
- 没有相似度阈值。
- 没有 chunk_id。
- 没有固定评估集，无法计算 recall@k/MRR。

## 4. 代码规模分布

根目录 28 个 Python 文件，共 4377 行，其中 2976 行为非空行：

| 文件 | 总行数 | 非空行 |
|---|---:|---:|
| `rag_assistant.py` | 618 | 285 |
| `main_api.py` | 368 | 298 |
| `production_source.py` | 286 | 226 |
| `generate_report.py` | 263 | 132 |
| `analysis_report.py` | 256 | 123 |
| `knowledge_search.py` | 254 | 185 |
| `main.py` | 218 | 161 |
| `database.py` | 192 | 148 |
| `database_manager.py` | 180 | 152 |
| `semantic_search.py` | 175 | 119 |
| `visualization.py` | 171 | 121 |
| `anomaly_analysis.py` | 170 | 137 |
| `llm_report_generator.py` | 169 | 128 |
| `sql_practice.py` | 144 | 123 |
| `database_query.py` | 139 | 108 |
| `report_parser.py` | 131 | 101 |
| `trend_analysis.py` | 116 | 98 |
| `report_generator.py` | 104 | 52 |
| `health_score.py` | 89 | 65 |
| `data_formatter.py` | 83 | 41 |
| `embedding_test.py` | 67 | 49 |
| `insert_history.py` | 57 | 42 |
| `check_database.py` | 33 | 27 |
| `test_parser.py` | 29 | 13 |
| `equipment_data.py` | 25 | 18 |
| `update_db.py` | 24 | 14 |
| `test_trend.py` | 16 | 10 |
| `llm_service.py` | 0 | 0 |

测试文件 `tests/test_data_pipeline.py` 为 435 行，其中 363 行为非空行。

## 5. 原问题清单逐条核对

| # | 原判断 | 结论 | 主要证据 | 影响 |
|---|---|---|---|---|
| 1 | RAG 与工程报告各有一套加载/切分/向量化 | 确认 | `rag_assistant.py:66-205`；`llm_report_generator.py:51-107`；后者再复用 `semantic_search.py` | 两套行为可能漂移，面试官会追问哪套是生产链路 |
| 2 | `knowledge_search.py` 与 `semantic_search.py` 重复加载 | 确认 | `knowledge_search.py:21`；`semantic_search.py:28`；`rag_assistant.py:66` 还有第三份 | 三处切分行为没有统一契约 |
| 3 | 按空行裸切，无长度上限、重叠和业务元数据 | 确认 | `knowledge_search.py:38`；`semantic_search.py:42`；`rag_assistant.py:83`；chunk 仅含 `source/content` | 文档变长后检索粒度失控，无法按设备/参数过滤 |
| 4 | 向量只在内存，每次启动重建 | 确认 | `llm_report_generator.py:23-25,57-68`；`semantic_search.py:60-75` | 冷启动慢，没有增量索引和可重复索引版本 |
| 5 | 没有检索评估 | 确认 | 仓库搜索 `recall`、`MRR` 无结果；只有 4 个手工烟雾问题 | 无法证明 recall@3 ≥ 0.85 |
| 6 | LLM 输出无结构/引用校验，可能编造事实 | 确认 | `llm_report_generator.py:113-165` 要求自然语言报告并直接返回字符串 | 无法拦截不存在的设备/批次，也无法展示依据 |
| 7 | 缺统一日志、异常处理和请求 ID | 确认 | 全仓库无 `logging`/`request_id`；`main_api.py:54-57,255-259` | 出问题无法追踪；且启动失败被静默吞掉 |
| 8 | 路径硬拼、配置散落 | 确认 | `production_source.py:19-21`；`database_manager.py:19-20`；`database.py:8-9`；另有 7 个文件重复 `BASE_DIR` | 部署和测试换环境成本高 |
| 9 | 测试不足，且无接口/RAG 回归 | 部分成立 | 已有 13 项接口/页面测试；但未覆盖 `/diagnose`、`/history`、详情页、503/422，也没有 RAG 测试 | “无接口测试”应纠正为“接口覆盖不完整” |
| 10 | 无 Dockerfile、CI、Makefile | 确认 | 根目录不存在这些文件；`requirements.txt` 未锁版本 | 新环境无法一条命令复现 |
| 11 | 仪表盘不展示诊断历史与引用 | 部分成立 | `dashboard.html` 无报告/引用；`/history` 和 `/diagnosis_detail/{id}` 已有报告视图 | 第五层成果不在主看板，引用来源完全缺失 |
| 12 | 学习脚本与生产模块混放 | 确认 | 28 个根目录 Python 文件；没有 `scripts/`；存在空 `llm_service.py`、空 `equipment.db`、`dashboard.html.bak` | 仓库像练习场，模块边界不清 |

## 6. 新发现的问题

排序原则：优先考虑面试可信度、事实安全、可复现性和后续返工成本。

| 优先级 | 问题 | 证据 | 影响 | 建议阶段 |
|---|---|---|---|---|
| P1-A | 启动初始化异常被 `pass` 吞掉 | `main_api.py:54-57` | 服务看似启动，后续接口才以 503 暴露；排障丢失上下文 | P1 |
| P1-A | 每次查询前重复读取完整外部文件 | `database_query.py:23`；`database_manager.py:73-87` | 每次查询先哈希、再解析全文件；10 万行场景会重复 I/O 和校验 | P1/P3 |
| P1-A | 无统一 request_id 和结构化日志 | 全仓库无 `logging`/`request_id` | API、同步、LLM 故障无法串联 | P1 |
| P1-A | 项目实际未进入当前 Git 历史 | `git rev-parse` 显示上层 `D:/Demo`；项目文件全部为 `??` | P1 的 CI 无法直接生效，也没有可回退基线 | P1 |
| P1-B | 响应无统一 envelope/Pydantic response model | `main_api.py` 直接返回不同形状 dict；错误是 FastAPI 默认 `detail` | 前后端契约弱，难以版本化 | P1/P3 |
| P1-B | 依赖未锁定且直接依赖缺失 | `requirements.txt` 与 import 审计不一致 | 新环境不可复现，Docker/CI 不稳定 | P1 |
| P1-B | 图表依赖外部 CDN | `templates/dashboard.html:8` 使用 jsDelivr | 离线/内网环境图表演示失效 | P1/P3 |
| P4-A | 检索无阈值，任何问题都返回 top 3 | `semantic_search.py:99-111` | 无依据也会被送入 Prompt | P4 |
| P4-A | 无 chunk_id、引用传播或原文定位 | chunk 只有 `source/content`；报告接口不返回引用 | 无法做到“每条结论挂 chunk_id” | P4/P5 |
| P5-A | 无结构化输出 schema 和事实实体校验 | `llm_report_generator.py:150-165` | 可能输出不存在的设备号/批次号 | P5 |
| P5-A | 无降级链、超时、重试、token/成本统计 | `main_api.py:255-259`；`llm_report_generator.py:150` | 无 key/断网直接 503；无法展示成本和延迟 | P5 |
| P5-A | `rag_assistant.py` 在 import 时创建 OpenAI client | `rag_assistant.py:23-37` | 无 key 时学习脚本可能在导入阶段失败，错误不友好 | P4 |
| P2-A | 数据质量只做“首个错误即中止”，无失败分布 | `production_source.py:243-279` | 无法返回拒绝记录数和原因分布，做不了 `/api/data-quality` | P2 |
| P2-A | 设备编号格式、工艺枚举、温度合理范围未校验 | `production_source.py:169-240` | 合法性依赖约定，脏数据可进入统计 | P2 |
| P2-A | 生产表没有事件/生产时间列 | `database_manager.py:36-47` | P3 的时间范围过滤和排序缺少数据基础 | P2/P3 |
| P2-A | 历史诊断库存在测试数据和风险等级不一致 | `diagnosis_history.db` 有 `TEST-DB-CHECK`；13 条有效记录中 3 条评分与风险不匹配 | 报告历史和统计可信度受损 | P2 |
| P3-A | 没有业务索引 | 两个 SQLite 数据库 `PRAGMA index_list` 均为空 | 设备、批次、历史查询在大数据量下退化 | P3 |
| P3-A | 没有分页、排序、时间过滤和 data-quality API | 路由清单中没有这些能力 | 与目标接口完整度不一致 | P3 |
| P3-A | 主仪表盘无报告历史、扣分明细、空状态引用 | `dashboard.html` 只展示生产分析；引用没有数据结构 | AI 成果不可在 Demo 主流程中验收 | P3 |
| P1-B | 缺失/空文件造成仓库噪声 | `llm_service.py` 0 行；`equipment.db` 0 字节；`dashboard.html.bak` | 面试官会怀疑代码是否为最终版本 | P1 |

## 7. 接口与测试覆盖基线

当前实际存在 11 个路由定义：

1. `/health_history/{equipment_id}`
2. `/`
3. `/healthz`
4. `/api/data-source`
5. `/api/equipment`
6. `/api/equipment/{equipment_id}/analysis`
7. `/health/{equipment_id}`
8. `/diagnose/{equipment_id}`
9. `/dashboard`
10. `/history`
11. `/diagnosis_detail/{record_id}`

原需求契约只列了 10 个路径，遗漏详情页。该额外接口可以保留，但最终文档
必须写全。

自动化测试已覆盖：

- `/`
- `/healthz`
- `/api/data-source`
- `/api/equipment`
- `/api/equipment/{id}/analysis`
- `/dashboard`
- `/health_history/{id}`
- 无效设备的 404

自动化测试未覆盖：

- 有效 `/health/{id}`
- `/diagnose/{id}`
- `/history`
- `/diagnosis_detail/{id}`
- 数据源不可用时的 503
- FastAPI 请求校验失败时的 422
- 任何 RAG 检索行为

## 8. 依赖与模块边界判断

通过本地 import 关系分析，主 API 实际生产链路为：

```text
main_api
├── production_source
├── database_manager
├── database_query
├── anomaly_analysis
├── health_score
├── trend_analysis
├── database
├── equipment_data
└── llm_report_generator
    └── semantic_search
```

当前没有被任何本地模块引用的根目录文件包括：

`analysis_report.py`、`check_database.py`、`data_formatter.py`、
`embedding_test.py`、`generate_report.py`、`insert_history.py`、
`knowledge_search.py`、`llm_service.py`、`rag_assistant.py`、
`report_generator.py`、`sql_practice.py`、`test_parser.py`、
`test_trend.py`、`update_db.py`、`visualization.py`。

其中部分是有保留价值的学习/导出脚本，不应直接删除；P1 应移动到
`scripts/learn/` 或 `scripts/tools/`，并明确入口和使用说明。

## 9. 建议修复顺序

### 第一优先：P1-A 将现状变成可追踪基线

1. 规划 `app/` 目录和兼容入口，不让 API 路径变化。
2. 建立 `config.py`，统一路径、阈值、模型名、密钥和运行环境。
3. 增加结构化日志、request_id 和统一异常处理，移除静默 `pass`。
4. 建立独立 Git 基线，避免继续在未跟踪状态下修改。
5. 保持测试全绿后再做文件迁移。

### 第二优先：P1-B 建立可复现运行与质量门禁

1. 锁定生产/dev 依赖，补齐直接依赖。
2. 增加 Makefile、Dockerfile、Compose 和 CI。
3. 增加覆盖率、lint 和测试命令。
4. 把学习脚本归档到 `scripts/learn/`，清理空文件和备份文件。

### 第三优先：P2/P3 数据可信度和接口完整度

1. 补齐数据质量报告、错误分布和生产时间字段。
2. 处理历史库脏数据，不删库，用迁移/校验修复。
3. 增加索引、分页、排序、时间过滤和统一响应模型。
4. 给仪表盘增加扣分明细、诊断历史与引用占位。

### 第四优先：P4/P5 RAG 与大模型可控性

1. 先建立统一 RAG 管线和检索测试集，不直接扩展 UI。
2. 在检索指标稳定后接入结构化 LLM 输出、引用和降级链。
3. 最后制作引用展示、指标报告和演示脚本。

## 10. P0 验收结论

当前项目可以被准确定位为：

- 一个可运行的课程式/个人模拟工业数据平台；
- 数据链路、规则评分、批次趋势和基础 API 已有较好测试；
- AI/RAG 仍处于“能演示、不能证明、不能约束”的阶段；
- 工程化交付、可观测性和模块边界尚未达到简历级项目标准。

本轮没有修改业务代码。P1 未开始，等待确认后再按
“计划 → 确认 → 实施 → 验收 → 汇报”推进。
