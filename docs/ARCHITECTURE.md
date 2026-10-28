# 系统架构

## 1. 定位

这是一个使用模拟生产数据构建的半导体设备生产分析与异常识别平台，
用于展示数据处理、SQL、API、规则分析、RAG 和大模型输出控制的工程实现。
它不是真实 MES、SCADA 或晶圆厂生产系统。

## 2. 五层架构

```mermaid
flowchart TB
    subgraph L1["1. 设备数据层"]
        CSV["CSV / JSON 模拟生产数据"]
        KB["模拟设备与工艺知识库"]
    end

    subgraph L2["2. Python 处理层"]
        Validate["字段校验与数据质量报告"]
        SQLite["SQLite 查询缓存与索引"]
        Rules["异常规则 / 评分 / 趋势"]
    end

    subgraph L3["3. 后端服务层"]
        API["FastAPI JSON API"]
        Obs["JSON 日志 / request_id / 统一异常"]
    end

    subgraph L4["4. 展示层"]
        Dash["设备仪表盘"]
        History["诊断历史与 chunk 原文"]
    end

    subgraph L5["5. AI 智能层"]
        Chunk["语义切分"]
        Index["持久化向量索引"]
        Hybrid["向量 + BM25 混合检索"]
        LLM["LLM 结构化报告"]
        Fallback["规则降级"]
    end

    CSV --> Validate --> SQLite --> Rules
    KB --> Chunk --> Index --> Hybrid
    Rules --> API
    Hybrid --> LLM
    Rules --> LLM
    LLM --> Fallback
    API --> Dash
    API --> History
    Obs --> API
```

## 3. 数据处理流

```mermaid
sequenceDiagram
    participant U as 用户/系统
    participant A as FastAPI
    participant S as 数据源校验
    participant D as SQLite
    participant R as 规则引擎

    U->>A: 查询设备/批次/时间范围
    A->>S: 检查文件哈希
    S->>S: 字段、类型、范围、唯一性校验
    alt 文件有效且内容变化
        S->>D: 事务内同步数据并更新 meta
    else 文件无效
        S-->>A: 拒绝原因与质量报告
        A-->>U: 业务接口 503 / 质量接口 200
    end
    A->>D: 索引过滤、分页与排序
    D-->>A: 生产记录
    A->>R: 异常、评分、趋势、扣分明细
    R-->>A: 确定性事实
    A-->>U: JSON / 仪表盘
```

## 4. RAG 与 LLM 流

```mermaid
sequenceDiagram
    participant R as 规则事实
    participant P as RAG管线
    participant L as DeepSeek
    participant V as Schema校验
    participant F as 规则降级

    R->>P: 设备、异常、批次、阈值
    P->>P: 文档哈希检查
    P->>P: 切分/索引/混合检索
    P-->>R: chunk_id、来源、分数
    R->>L: 事实 + 检索上下文 + JSON Schema
    alt JSON合法且事实一致
        L-->>V: 结构化报告
        V-->>R: 已验证报告与引用
    else 首次输出非法
        V-->>L: 校验错误反馈，重试一次
        alt 第二次合法
            L-->>V: 结构化报告
        else 仍失败/断网
            V->>F: 降级
            F-->>R: 确定性结构化摘要
        end
    end
```

## 5. 存储

### 生产数据

`database/production.db`

- `wafer_production`
- `data_source_meta`
- 索引：设备、批次、生产时间、设备+时间

### 诊断与模型统计

`diagnosis_history.db`

- `diagnosis_history`
- `llm_call_stats`

旧库使用增量 `ALTER TABLE`，不删除历史数据。

### RAG 索引

`data/rag_index/`

- `manifest.json`
- `chunks.json`
- `vectors.npy`

索引由文件内容哈希触发刷新；当前规模采用 NPY 精确检索，不引入外部向量数据库。

## 6. 关键设计决策

完整记录见 [DECISIONS.md](DECISIONS.md)。

- 结构化事实只来自确定性规则模块。
- 页面不调用 LLM，避免打开仪表盘产生费用和外部依赖。
- LLM 只能组织语言和提供初步检查方向，不得修改评分。
- 脏数据不使用旧库冒充当前结果。
- 排序字段使用白名单，避免 SQL 注入。
- 旧 API 保持兼容，新记录接口使用 `data/meta` envelope。
- RAG 使用向量 + BM25，并用负例控制无关召回。

## 7. 边界与扩展

适用：

- 个人作品集和面试技术演示；
- 中小规模模拟工业数据分析；
- RAG/LLM 输出控制教学。

不适用：

- 真实晶圆厂生产控制；
- 高频时序采集和 SCADA 实时闭环；
- 大规模并发向量检索；
- 不经人工确认的维修或工艺调整。
