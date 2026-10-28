# 测试与评估基线

## 1. 一键门禁

```bash
make check
make rag-regression
```

Windows 无 Make：

```powershell
python scripts/dev.py check
python scripts/dev.py rag-regression
```

`make check` 执行：

1. Python compileall；
2. pyflakes；
3. 全量单元/接口测试；
4. 核心分析模块行覆盖率门禁。

## 2. 当前基线

- 测试数：65
- 通过数：65
- 核心分析行覆盖率：86.67%
- 覆盖率工具：标准库 `trace`
- 覆盖率阈值：80%

当前环境无法下载 coverage.py 和 pytest。使用 `trace` 是为了让本地和 CI
在没有额外下载的情况下执行门禁，不代表它等价于 coverage.py 的分支覆盖。

标准库 `trace` 对 FastAPI TestClient 工作线程中的 API 行记录不完整，因此
报告中 `app/api/main.py` 的 0% 是测量工具限制。接口行为已通过 TestClient
断言覆盖，不应把这个数字解释成 API 未测试。

## 3. 测试分层

### 数据层

- CSV/JSON 读取；
- 中文字段别名；
- 缺字段、空文件、非法数字、范围越界；
- 非法设备编号和未知工艺；
- 重复批次；
- 无效时间；
- 哈希同步与文件变化刷新；
- 旧生产库增量迁移；
- 旧诊断库增加引用和结构化报告字段；
- 脏数据不污染业务表。

### 规则与分析层

- 异常事件和异常批次口径；
- 设备评分、风险边界；
- 设备级阈值覆盖；
- 逐事件扣分明细；
- 趋势稳定、下降、回升和数据不足；
- 固定样本回归快照。

### 接口与页面层

已覆盖：

- `/`
- `/healthz`
- `/dashboard`
- `/history`
- `/diagnosis_detail/{id}`
- `/health/{id}`
- `/health_history/{id}`
- `GET /diagnose/{id}`（只读预览）
- `POST /diagnose/{id}`（落库）
- `/api/data-source`
- `/api/data-quality`
- `/api/production/records`
- `/api/equipment`
- `/api/equipment/{id}/analysis`
- `/api/knowledge/search`
- `/api/knowledge/status`
- `/knowledge/chunk/{id}`
- `/api/llm-stats`

异常路径覆盖 400、404、422、503，以及脏数据启动时的 503。

### RAG

- 语义段落与长度限制；
- chunk 元数据和稳定 ID；
- 索引复用，不变时不重新 embedding；
- 文件变化刷新；
- 混合检索；
- 元数据过滤；
- 无关问题 `no_match`；
- 50 条七分类段落级评估集；
- Prompt 中的真实 chunk_id。

### LLM 控制

- JSON Schema；
- 未知设备、批次、chunk_id；
- 错误评分和风险；
- 代码围栏 JSON；
- 非法输出一次修复重试；
- 无 key 降级；
- RAG 与 LLM 同时不可用降级；
- 调用统计持久化；
- 结构化报告和引用持久化。

## 4. RAG 两层评估

CI 回归：

```text
python scripts/evaluate_rag.py --embedder deterministic --fail-under 0.80
```

不需要下载向量模型，但使用同一 50 条问题、混合检索和 5 条负例。

当前 CI 基线（20 篇文档 / 102 chunk）：

- recall@1/@3/@5：0.80 / 0.86 / 0.88
- MRR：0.8317
- 负例 no-match：1.0
- P95：约 15.60 ms（语料变大后单次检索耗时上升，仍是毫秒级）

真实语义模型评估：

```bash
make rag-eval
```

当前本机基线：**未复测**。评测机没有安装 `torch` 与
`sentence-transformers`，语义模型路径无法运行，因此不给出数字。
历史版本在 3 篇文档上记录过 recall 1.0，那是结构性满分，已废弃。

50 条评估集仍围绕当前模拟知识库构建，指标偏乐观。真实简历中
必须同时注明数据集规模和模拟边界。

## 5. 固定数据回归

`tests/fixtures/expected_regression.json` 锁定：

- 30 条有效记录；
- 3 台设备；
- ETCH-01/02/03 的评分和异常数；
- ETCH-02 的 12 点累计评分序列。

规则或数据处理改动导致结果变化时，回归测试会失败，要求显式更新快照并
解释原因。
