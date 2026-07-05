# Evidence-driven Iterative Retrieval

阶段 6 在现有 Evidence Gate 和单次 Query Rewrite 之上增加了“有界二次检索”。它不是开放式 Agent：Planner 和 Tool Router 仍不接管真实路由，新增循环默认关闭。

## 默认行为与开关

`ENABLE_ITERATIVE_RETRIEVAL=false` 是默认值。此时 `/api/chat`、`/api/search` 和原有 Graph 路径保持现状，原先证据不足时的一次 Rewrite 逻辑仍然保留。

实验环境中可通过环境变量开启：

```powershell
$env:ENABLE_ITERATIVE_RETRIEVAL="true"
```

开启后，只有 Evidence Gate 判定证据不足、建议 `rewrite_and_retry`，并且轮数、Rewrite 次数、工具调用数和超时预算全部允许时，才会追加一轮检索。两轮证据按真实 `chunk_id` 去重并使用已有检索分数排序，不生成或补写 provenance。

阶段 7 增加了规则式标识符过滤：纯单字符数字、`PLC`、`manual`、手册、参数、故障、报警、设备以及过宽泛的 S7 型号不能单独触发重试；`MB_CLIENT`、`16#80C8`、`ID`、`IP`、`DB`、`PORT`、`BAUD` 和 `502` 等有区分度标识会保留。判断过程不调用 LLM，Trace 同时保留原始缺失词、过滤后缺失词和被忽略泛词，便于审计。

安全类和越界类请求不会进入检索或模型调用。控制器最多受以下配置约束：`max_agent_rounds`、`max_tool_calls`、`max_llm_calls`、`agent_timeout_seconds` 和 `max_rewrites`。

## Trace

Trace 会记录 `rounds`、`retrieval_rounds`、`rewrite_triggered`、`rewritten_queries`、`evidence_assessments`、`stop_reason`、`budget` 和 `tool_calls`。这些字段用于解释为何重试或停止；它们不改变旧客户端的必填输入。

## A/B 评测

```powershell
.\.venv\Scripts\python.exe scripts\eval_iterative_retrieval.py
```

脚本使用同一份 formal eval 数据和已有 ranking 指标函数，对比现有一次 Rewrite baseline 与开启有界迭代后的 candidate，生成：

- `reports/iterative_retrieval_eval.json`
- `reports/iterative_retrieval_eval.md`

该实验衡量证据不足时补充检索的收益，不调用 LLM，也不代表最终问答准确率。报告同时给出过滤前后 Retry Trigger Rate、泛词阻断数和 Unnecessary Retry Rate。二次检索会增加计算成本和响应延迟，应把 Strict Recall/MRR/nDCG/Top1 的变化与 Retry Trigger Rate、P50/P95 延迟一起判断。迭代检索仍默认关闭。
