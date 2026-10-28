# 大模型输出可控性

## 1. 事实边界

确定性规则模块先生成以下事实：

- 设备编号
- 健康评分和风险等级
- 适用阈值
- 异常事件和批次
- 扣分明细
- 检索命中的 chunk_id

大模型只负责组织解释和检查建议，不参与评分、异常计数或阈值判断。

## 2. Prompt 模板

模板独立存放于：

```text
prompts/equipment_diagnosis.md
```

模板通过 `$facts_json`、`$contexts` 和 `$schema_json` 注入事实、检索上下文
与输出 Schema。Prompt 明确禁止编造设备、批次、维修结果和真实工厂经验。

## 3. JSON 强校验

Pydantic 模型位于 `app/llm/schema.py`，使用：

- `extra="forbid"` 拒绝未声明字段。
- 评分范围、风险枚举、模拟数据标记和列表长度校验。
- 设备编号必须与确定性事实一致。
- 批次号只能来自当前设备真实批次。
- chunk_id 只能来自本次检索结果。
- 有检索结果时，每条 finding 必须引用至少一个 chunk_id。
- 正文中出现未知 BATCH/LOT/WAFER 编号会被拦截。

校验失败后最多进行一次带错误反馈的修复重试。

## 4. 降级链

```text
DeepSeek 结构化输出
  -> Schema/实体/引用校验
  -> 一次修复重试
  -> 确定性规则摘要
```

无 key、断网、RAG 模型不可用或持续非法输出均不会导致 `/diagnose`
返回 500；报告会标记 `provider="rules_fallback"` 和 `fallback=true`。

## 5. 引用

诊断结果返回 `report_json`、Markdown 报告和 `references`。
`references` 中含 chunk_id、来源、章节、相似度和原文字符位置；
诊断详情页可链接到 `/knowledge/chunk/{chunk_id}` 查看原文。

## 6. 调用统计

`GET /api/llm-stats` 返回：

- attempts / successes / fallbacks
- success_rate / fallback_rate
- P50 / P95 延迟
- prompt / completion tokens
- provider 分布
- 估算成本

输入与输出每百万 token 单价通过环境变量配置，默认 `0`。未配置真实价格时，
不得把 `estimated_cost` 当成供应商账单。

## 7. 验收样例

- 无 key/断网：返回规则降级报告。
- 首次输出引用 `BATCH-999`：校验失败并重试。
- 第二次输出合法：采用第二次结果，provider 为 `deepseek`。
- 重试仍非法：规则降级，并记录 validation error。
