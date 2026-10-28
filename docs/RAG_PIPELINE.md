# RAG 工程管线

## 1. 单一主链路

生产代码只使用：

```text
knowledge_base/
  -> app/rag/chunking.py
  -> app/rag/index.py
  -> app/rag/retrieval.py
  -> app/rag/pipeline.py
  -> API / 诊断 Prompt
```

`scripts/learn/knowledge_search.py` 和 `scripts/learn/rag_assistant.py`
只保留学习价值，不再被生产 API 调用。

## 2. 切分

- 按空行和标题/编号边界形成语义段。
- 单块默认上限 480 字符，重叠 80 字符，可配置。
- 每个 chunk 包含：
  - 稳定 `chunk_id`
  - 来源文件与相对路径
  - 文档标题、章节
  - 设备类型
  - 参数类型
  - 主题
  - 原文字符起止位置

当前知识库内容较短，但配置和测试已覆盖超长文本切分。

## 3. 持久化索引

索引默认位置：`data/rag_index/`

包含：

- `manifest.json`：文件哈希、模型名、切分配置、构建时间
- `chunks.json`：chunk 和元数据
- `vectors.npy`：归一化向量矩阵

启动时不加载模型。首次检索先比对知识文件签名（mtime + size），未变化直接
加载磁盘索引，变化或模型/切分配置改变时重建；哈希只在构建期计算，不进入
查询热路径。文件使用临时文件加 `os.replace` 原子更新。

## 4. 混合检索

- 向量余弦相似度
- BM25 关键词分数，中英文使用 jieba 搜索分词
- 默认权重：向量 0.65、关键词 0.35
- 元数据过滤：来源、设备类型、参数类型；值可以是单个期望值，也可以是
  可选值列表（例如诊断链路传 `equipment_type=[当前设备, general]`）
- 无词法证据时，语义分数必须达到更高阈值，减少无关查询误召回
- 无可靠结果时返回 `no_match=true` 和空 `hits`

## 5. 引用

检索结果返回 `chunk_id`、原文位置、章节、分数和截取正文。
`GET /diagnose/{equipment_id}` 在报告之外返回 `references`；检索按设备过滤，
过滤后为空时自动放宽一次，并在 `retrieval.filters_relaxed` 中标记；
Prompt 要求使用知识时标注 chunk_id，无依据时明确说明。

逐句引用和结构化输出校验属于 P5。

## 6. 接口

```text
GET /api/knowledge/search?question=温度异常怎么检查&top_k=4
GET /api/knowledge/status
GET /knowledge/chunk/{chunk_id}
```

检索接口支持：

- `source`
- `equipment_type`
- `parameter_type`

## 7. 评估

固定数据集：`evaluations/rag_questions.json`

- 30 条问题
- 温度、压力、良率、维护、工艺五类，各 6 条
- 指标：recall@1/@3/@5、MRR、P50/P95 延迟
- 5 条无关问题用于验证 `no_match`
- 门禁：recall@3 ≥ 0.85，负例 no-match ≥ 0.80

运行：

```bash
make rag-eval
```

评估结果写入 `output/rag_evaluation.json`。

当前固定基线：

- recall@1/@3/@5：1.0 / 1.0 / 1.0
- MRR：1.0
- 检索 P50/P95：约 11.21 / 13.15 ms
- 5 条负例：全部 `no_match`

这些结果来自模拟知识库和固定问题集，不代表真实工厂技术文档场景的准确率。

所有知识库和生产数据均为模拟学习资料，不代表真实工厂规范。
