# Agentic Shadow Plan Evaluation

> 本报告只评估影子Intent、候选工具与Bounded Planner，不代表最终问答准确率。

- API调用：否
- 检索调用：否
- 工具执行：否
- LLM调用：否
- Planner应用到真实路由：否

## Metrics

| Metric | Value |
|---|---:|
| Total Cases | 24 |
| Intent Accuracy | 1.0000 |
| Tool Selection Accuracy | 1.0000 |
| Plan Valid Rate | 1.0000 |
| Safety Block Plan Accuracy | 1.0000 |
| Out-of-scope Block Plan Accuracy | 1.0000 |
| Avg Plan Steps | 1.1250 |
| Max Plan Steps | 2 |
| Unnecessary Tool Rate | 0.0000 |
| Budget Violation Count | 0 |
| Tool Whitelist Violation Count | 0 |
| Loop Violation Count | 0 |

## 指标边界

- `intent_accuracy`：预测intent与人工expected_intent完全一致的比例。
- `tool_selection_accuracy`：结构化plan工具序列与人工expected_tools完全一致的比例。
- `plan_valid_rate`：步骤、白名单、预算、安全阻断、shadow模式和applied=false均满足约束的比例。
- `unnecessary_tool_rate`：general_manual_search生成非单一search_manual计划的比例。
- `loop_violation_count`：step_id非连续或同一action在单个线性计划中重复的案例数。

本评测仅检查规则式Intent、候选路由和Bounded Planner的影子计划质量；不调用API、检索、工具或LLM，不代表最终问答准确率。
