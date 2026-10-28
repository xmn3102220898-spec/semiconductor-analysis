# 指标与复现方法

测量日期：2026-10-27  
环境：Windows，Python 3.12，当前项目模拟数据  
原则：以下数字均可通过命令重新测量，不是手工估算。

## 1. 测试与覆盖率

命令：

```powershell
python -X utf8 scripts/dev.py check
```

当前结果：

| 指标 | 数值 |
|---|---:|
| 测试数 | 78 |
| 通过数 | 78 |
| 失败数 | 0 |
| 测试耗时 | 约 3.50 s |
| 核心分析行覆盖率 | 86.47% (147/170) |
| 覆盖率阈值 | 80% |

测量说明：

- 当前使用 Python 标准库 `trace`。
- `app/api/main.py` 的 runner 线程行无法被 `trace` 完整捕获，因此文件表
  中的 0% 不能解释为没有接口测试。
- 覆盖门禁明确只针对 `app/analysis`，接口行为由 TestClient 断言覆盖。

## 2. API 延迟

命令：

```powershell
python -X utf8 scripts/bench_api.py
```

当前结果：

| 接口 | P50 | P95 | Max |
|---|---:|---:|---:|
| `/health/ETCH-02` | 6.421 ms | 6.951 ms | 7.147 ms |
| `/api/equipment/ETCH-02/analysis` | 6.546 ms | 7.374 ms | 7.421 ms |
| `/api/production/records` | 4.638 ms | 5.182 ms | 6.025 ms |
| `/api/data-quality` | 2.824 ms | 3.110 ms | 4.051 ms |

说明：

- 使用 TestClient 串行 30 次，不含真实网络 RTT。
- 不包含 RAG 首轮模型加载和 LLM 外部请求。

## 3. 10k / 100k 查询

命令：

```powershell
python -X utf8 scripts/bench_scale.py
```

当前结果：

| 行数 | 设备分页 P50 | 设备分页 P95 | 时间范围 P50 | 时间范围 P95 |
|---:|---:|---:|---:|---:|
| 10,000 | 3.562 ms | 3.854 ms | 0.954 ms | 1.067 ms |
| 100,000 | 24.202 ms | 24.478 ms | 18.703 ms | 19.060 ms |

数据通过临时 SQLite 生成，不写入项目数据库。

## 4. RAG 真实语义模型（本轮未复测）

命令：

```text
$env:HF_HUB_OFFLINE="1"
python -X utf8 scripts/evaluate_rag.py --embedder semantic --fail-under 0.80
```

状态：**未复测**。本轮语料扩容后，评测机上没有安装 `torch` 与
`sentence-transformers`，语义模型路径无法运行，因此本节不再给出数字。

历史版本（3 篇文档、16 个 chunk、30 题、top_k=5）曾记录
recall@1/@3/@5 均为 1.0，但那是结构性满分：候选片段数与 top_k 同阶，
分数是算出来的而不是检出来的。该数字已废弃，不再作为卖点引用。

复测方式：在有模型的机器上执行上面的命令，结果写入
`output/rag_evaluation.json`，其中 `embedding_model` 会显示实际模型名。

## 5. RAG CI 确定性回归

命令：

```text
python -X utf8 scripts/evaluate_rag.py --embedder deterministic --fail-under 0.80
```

当前结果（20 篇文档 / 102 个 chunk / 50 题）：

| 指标 | 数值 |
|---|---:|
| 问题数 | 50 |
| 分类 | 温度 8、压力 7、良率 5、设备 12、改写 8、干扰 6、多证据 4 |
| recall@1 | 0.80 |
| recall@3 | 0.86 |
| recall@5 | 0.88 |
| MRR | 0.8317 |
| 旧关键词口径 recall@3 | 0.82（仅对比，不作门禁） |
| 负例 no-match | 5/5 |
| P50 | 14.30 ms |
| P95 | 15.60 ms |

边界：

- 金标是段落级的：命中同文档的其它段落不算命中，避免「文档对就算对」。
- 改写类问题 recall@3 只有 0.375：确定性嵌入器只能做词面匹配，无法把
  「热场读数」映射到「温度」。这是该嵌入器的上限，不是检索逻辑回归。
- 数据集仍围绕本项目模拟知识库编写，指标偏乐观，不能外推为真实工厂
  文档准确率。

## 6. LLM 控制与统计

已自动化验证：

- Schema 不合法输出被拒绝；
- 不存在的设备、批次、chunk_id 被拒绝；
- 非法输出可修复一次；
- 无 key 或断网降级；
- RAG 与 LLM 同时不可用时仍返回规则报告；
- token、延迟、provider 和 fallback 持久化。

没有测量线上 DeepSeek 延迟和成本，因为本轮没有发起真实付费请求。
`/api/llm-stats` 中的 `estimated_cost` 默认是 0，只有配置
`LLM_INPUT_COST_PER_MILLION` 和 `LLM_OUTPUT_COST_PER_MILLION` 后
才有业务意义。

## 7. 数据规模

| 项目 | 数值 |
|---|---:|
| 设备 | 3 |
| 生产批次 | 30 |
| 知识文档 | 20 |
| RAG chunk | 102 |
| 向量维度 | 384 |
| 评估问题 | 50 |
| 负例问题 | 5 |

## 8. 不可宣称的指标

不得把以下内容写成真实工厂成果：

- 真实产线准确率；
- 真实故障预测准确率；
- 真实维护节省金额；
- 未配置真实单价时的 LLM 成本；
- 未实际运行的 Docker/CI 指标。
