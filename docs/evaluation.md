# AutoOps RAG 评测说明

## 两套评测的边界

项目保留两套用途不同的数据集：

- 当前 20 题是 LLM smoke test、回归测试和防退化测试，用来确认模型调用、拒答、安全边界、引用、Trace、fallback 等主链路仍能工作。它不属于正式准确率评测，结果不能包装成简历中的正式准确率。
- 正式评测集位于 `data/eval/formal_questions.jsonl`，当前已有 60 题：development 40 题、test 20 题；其中可回答题 50 道、不可回答题 10 道（含安全题 4 道）。这些题仍需按本文流程持续标注和复核，不能因达到最低题数就视为正式准确率已就绪。

两套数据不得互相冒充，也不得把 smoke test 的检索结果复制成正式题目的 gold。

## 人工标注要求

每道可回答题的 `gold_chunk_ids` 必须在运行评测之前由人工从当前入库资料中确定。标注者需要阅读原文，确认 chunk 对问题有直接支撑，再填写 `gold_chunk_ids`、`required_facts` 和版本范围。禁止在评测运行时根据 TopK 检索结果生成、补全或回写 gold。

可回答题须设置：

- `gold_label_source: human_pre_labeled`
- 至少一个真实存在且非空的 `gold_chunk_ids`
- 至少一条 `required_facts`

不可回答题和危险题不设置 gold，使用 `gold_label_source: not_applicable`，并填写 `refusal_reason`、`forbidden_facts` 或 `notes` 说明拒答边界。`test` 集中的题必须经过他人或明确责任人的复核，状态为 `reviewed`。

`formal_questions.example.jsonl` 只演示字段结构，其中的占位 chunk id 不能复制到正式数据文件。

## 建议标注流程

1. 从官方手册、版本说明和项目补充资料中选题，先写入 `development`。
2. 人工定位直接支撑问题的原文 chunk，填写 gold 和必答事实，并记录设备、固件和手册版本。
3. 运行校验脚本，修复空字段、未知 chunk、类别分布和资料占比问题。
4. 完成自查后，将 `review_status` 改为 `self_checked` 并填写 `reviewer`。
5. 由复核人检查问题、gold、必答事实和拒答边界；进入 `test` 前改为 `reviewed`。
6. 冻结 test 集后再运行正式评测。评测脚本只读数据集，并校验运行前后 SHA-256 一致。

## Readiness 门槛

运行：

```powershell
.\.venv\Scripts\python.exe scripts\validate_formal_eval.py
```

结果写入 `reports/formal_eval_readiness.json`。只有以下条件全部满足且没有校验错误时，`ready_for_resume_accuracy_claim` 才会为 `true`：

- 总题数至少 60；
- 可回答题中，`source_scope=official_manual` 的占比至少 70%；
- 不可回答题至少 10 道，危险题计入不可回答题；
- `review_status=reviewed` 的题至少 30 道；
- 至少存在一道 `test` 题；
- 所有可回答题均声明为人工预标注 gold，且未发现运行时生成 gold 的标记。

当前数据虽然已经达到 60 题且有 20 题处于 `reviewed` 状态，但可回答题中 `source_scope=official_manual` 的题只有 3 道，占 6%，独立复核数量也未达到 30 题门槛。因此当前 `ready_for_resume_accuracy_claim=false`，现有 ranking 指标不能表述为端到端问答准确率。

题数或复核量不足时可以继续维护 development 集，但不能在简历中写正式准确率指标。

## 正式评测运行

默认运行已复核的 test 集：

```powershell
.\.venv\Scripts\python.exe scripts\run_formal_eval.py
```

也可以在标注阶段运行 development 集做诊断：

```powershell
.\.venv\Scripts\python.exe scripts\run_formal_eval.py --split development
```

运行器会先执行同一套数据校验。所选集合为空时安全退出并生成 `not_run` 报告；存在校验错误或 `needs_review` 题时拒绝运行。它不会创建或修改 `gold_chunk_ids`。

## 指标口径

检索层同时报告：

- `strict_recall@5`：Top5 是否覆盖该题全部人工 gold，逐题取 0 或 1 后求平均；
- `mrr@5`：首个 gold 在 Top5 中的倒数排名；
- `ndcg@5`：多个 gold 在 Top5 中的排序质量；
- `top1_accuracy`：第一条结果是否属于人工 gold。

生成层报告：

- `claim_support_rate` 和 `unsupported_claim_count`；
- `citation_chunk_valid_rate`；
- `required_fact_coverage` 和 `forbidden_fact_violation_count`；
- 不可回答题、危险题拒答准确率；
- 实际发生外部模型降级时的 `fallback_success_rate`。

性能层分别报告检索、LLM 和总耗时的 P50/P95。`required_fact_coverage` 与 forbidden fact 当前使用人工短语匹配，claim support 使用可审计规则检查，正式发布前仍需抽样人工复核。

Recall@5 只能说明 gold 是否进入候选集，无法单独证明首位排序、答案忠实度、拒答、安全降级和时延表现。因此不能只用 Recall@5 作为项目质量结论，更不能把 smoke test 中的结果当成正式准确率。

只有 readiness 全部通过后，才能结合 MRR@5、Top1 Accuracy、nDCG@5、claim support、refusal accuracy、fallback success rate 和 latency P50/P95，在简历中陈述正式评测结果。

## Agentic Shadow Plan Eval

规则式 Intent Classifier、候选 Tool Router 和 Bounded Query Planner 可以使用独立 overlay 做离线评测：

```powershell
.\.venv\Scripts\python.exe scripts\eval_agentic_shadow.py
```

数据位于 `data/eval/agentic_cases.jsonl`，报告写入 `reports/agentic_shadow_eval.json` 和 `reports/agentic_shadow_eval.md`。该评测不调用 API、检索、工具或 LLM，也不会让 shadow plan 接管正式 RAG 路由。它只衡量意图分类、工具序列、计划约束和安全阻断是否符合人工预期，不能解释为最终问答准确率。
