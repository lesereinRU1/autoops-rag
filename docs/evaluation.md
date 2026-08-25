# AutoOps RAG 评测说明

## 评测边界

项目保留用途不同的评测集：

- `data/eval/application_questions.jsonl` 是 LLM smoke test / 回归集，用来检查模型调用、引用、拒答、安全、Trace 和降级机制（fallback），不属于正式准确率评测。
- `data/eval/formal_questions.jsonl` 是 formal evaluation：当前 60 题，development 40 题、test 20 题；其中可回答题 50 道、应拒答题 10 道，Safety 题 4 道。

smoke test 的检索结果不能复制成 formal 数据的人工标准答案（gold）。无论哪一层指标，当前项目都不能描述为生产级系统。

## 两层评测

### Retrieval Evaluation

这一层只回答“人工标注的证据有没有被检索到、排在什么位置”：

- `strict_recall@5`：Top 5 必须覆盖该题全部 `gold_chunk_ids`，逐题记 0/1 后求平均；
- `retrieval_hit_rate`：Top 5 至少命中一个 gold chunk 的题目比例；
- `mrr@5`：首个 gold chunk 在 Top 5 中的倒数排名；
- `ndcg@5`：存在多个 gold chunk 时的排序质量；
- `top1_accuracy`：第一条结果是否属于任一 gold chunk。

`strict_recall@5` 保留现有严格口径，不改成“命中任意一个 gold”。Retrieval Recall 不等于最终回答准确率：检索命中后，回答仍可能漏事实、引用错误、错误拒答或生成证据外内容。

### End-to-End Rule Evaluation

这一层调用 `/api/chat`，只计算可以被确定性规则审计的指标：

- `citation_correctness_rate`：回答引用是否真实映射到本次 Evidence 的 source/chunk/document/page；
- `required_fact_coverage`：回答覆盖了多少条由 gold Evidence 支持的 `required_facts`；
- `technical_identifier_accuracy`：故障码、参数名、数值、范围、单位和型号的精确匹配；
- `multi_hop_evidence_coverage`：多跳题召回了多少必要 gold evidence；
- `refusal_accuracy`：应拒答/应回答的决策是否正确；
- `false_accept_rate`：应拒答却回答的比例；
- `false_reject_rate`：应回答却拒答的比例；
- `claim_support_rate`：仅检查规则可识别的引用、技术标识和数值支持情况。

`claim_support_rate` 不是完整 Answer Faithfulness。`required_fact_coverage` 是规则型 coverage，不是最终回答准确率。当前不启用 LLM-as-a-judge；报告固定记录 `llm_judge.enabled=false`。

## 数据集冻结与 Dev/Test 边界

冻结信息位于 `data/eval/formal_eval_manifest.json`：

- dataset version：`formal_eval_v1`
- dataset SHA-256：`3b33876cd584e6215ef03a8bb07d0566aa57371957e606196c37b6f26641a4d9`
- case count：60
- splits：development 40、test 20

runner 会同时校验 manifest、实际文件 hash、case count、split 数量，并确认评测前后 hash 未变化。修改正式题目后必须更新版本或 manifest，不能继续横向比较旧结果。

- development set 用于规则开发、错误分析和参数调整；
- test set 只用于冻结后的最终报告；
- 根据 test 结果反复修改阈值后，不能继续称它为“未见测试集”。

## 当前题型分布

| 数据集 category | 报告分组 | 总数 | development | test |
|---|---|---:|---:|---:|
| `alarm_code` | `fault_code` | 7 | 3 | 4 |
| `official_parameter` | `parameter` | 15 | 14 | 1 |
| `table_query` | `table` | 3 | 2 | 1 |
| `natural_language_rewrite` | `semantic` | 14 | 10 | 4 |
| `cross_section_procedure` | `multi_hop` | 10 | 5 | 5 |
| `unanswerable_version` | `unanswerable` | 4 | 2 | 2 |
| `unanswerable_scope` | `out_of_scope` | 2 | 1 | 1 |
| `unsafe_request` | `safety` | 4 | 2 | 2 |
| `version_conflict` | `version_conflict` | 1 | 1 | 0 |

样本不足必须在报告中保留：表格题仅 3 道、越界题仅 2 道、版本冲突仅 1 道且没有 test 样本、参数题 test 仅 1 道。10 道多跳题中只有 6 道具有至少两个必要 gold chunk；其余多跳题的 `multi_hop_evidence_coverage` 为 `null`，不记 0。

## 人工标注要求

每道可回答题的 `gold_chunk_ids` 必须在评测前人工确定。标注者需要阅读原文，确认 chunk 对问题有直接支撑，再填写 `gold_chunk_ids`、`required_facts` 和版本范围。禁止根据运行时 Top K 生成、补全或回写 gold。

可回答题须设置：

- `gold_label_source: human_pre_labeled`
- 至少一个真实存在且非空的 `gold_chunk_ids`
- 至少一条 `required_facts`

不可回答题和 Safety 题不设置 gold，使用 `gold_label_source: not_applicable`，并通过 `refusal_reason`、`forbidden_facts` 或 `notes` 说明边界。test 题必须是 `reviewed`。

当前技术标识不是独立人工 gold field。评测器从 `required_facts` 保守抽取后，报告必须标记 `technical_identifier_source: "derived from required_facts"`；没有可识别标识时相关字段为 `null`。

## Citation Correctness 口径

评测器按 source index 合并正文和 `4. 引用来源` 清单，避免 `[来源N]` 被重复计数。每个唯一 source 需要满足：

1. source index 在本次 Evidence 范围内；
2. 显式 `chunk_id` 与该 source 对应的 Evidence 一致；
3. 显式 document/page 与该 source 对应的 Evidence 一致；
4. 不存在非法引用编号、未知 chunk 或无法解析的引用格式。

逐题输出 `citation_valid`、`citation_invalid_count`、引用诊断和 Citation Guard 是否执行 `fallback_local_extractive`。拒答时 Citation 不适用，字段为 `null`。

## Required Fact 与规则型事实支持

`required_fact_coverage` 使用离线确定性规范化、同义短语和原子事实匹配。只有 gold Evidence 支持且回答覆盖的事实才计入。报告同时保留更严格的 `required_fact_exact_coverage`，便于诊断 checker false negative。

`claim_support_rate` 继续使用窄范围规则检查引用、工业标识符、版本、状态码和数值。它不会被改名或包装为完整 Answer Faithfulness；自然语言语义蕴含仍需要人工抽查，未来如增加 LLM Judge 也只能作为默认关闭的独立可选指标。

## Refusal Correctness 口径

逐题使用完整混淆矩阵：

- 应拒答且实际拒答：`correct`
- 应拒答但实际回答：`false_accept`
- 应回答但实际拒答：`false_reject`
- 应回答且实际回答：`correct`

报告按 `safety`、`out_of_scope`、`evidence_insufficient` 分开汇总。对单题不适用的 `false_accept` 或 `false_reject` 使用 `null`。

## 逐题结果 Schema

每题至少保留：

```text
case_id, category, category_group, answerable, expected_refusal,
retrieval_hit, strict_recall@5, reciprocal_rank, citation_valid,
citation_invalid_count, required_fact_coverage,
technical_identifier_accuracy, multi_hop_evidence_coverage,
refusal_correct, false_accept, false_reject, latency,
stop_reason, rewrite_count, tool_calls, error
```

字段不适用或请求失败时使用 JSON `null`，不使用 0 冒充结果。完整 JSON/Markdown 报告保存在文件；EvaluationRepository 只保存 run metadata、逐题状态/关键指标和汇总，不保存大段 Answer、Evidence 或 Prompt。

## 运行方式

只检查 dataset、manifest、split 和运行条件，不调用 API、不生成指标：

```powershell
.\.venv\Scripts\python.exe scripts\run_formal_eval.py --dry-run --split test
```

正式执行 test split：

```powershell
.\.venv\Scripts\python.exe scripts\run_formal_eval.py --split test
```

development 诊断：

```powershell
.\.venv\Scripts\python.exe scripts\run_formal_eval.py --split development
```

如果缺少 `data/processed/chunks.jsonl`，dry-run 会明确返回 `execution_ready=false`；正式执行会拒绝运行，不生成新的 Recall/Citation/Faithfulness 数值。

## Readiness

`ready_for_resume_accuracy_claim=true` 仍要求：至少 60 题、官方来源可回答题占比至少 70%、至少 10 道不可回答题、至少 30 道 reviewed 题、存在 test split，且所有可回答题均使用人工预标注 gold。

当前为 60 题、20 道 reviewed，官方来源可回答题只有 3 道，占 6%，因此 `ready_for_resume_accuracy_claim=false`。这不表示脚本失败，但禁止宣传生产级准确率。

## 历史报告状态

旧 dataset hash `e251df9e9e495644108773becc1880db35d4af0429068a42b881e4501bea4063` 对应的 formal/ranking 数值只能标记为 stale/historical，不能作为当前正式结果。当前 `reports/formal_evaluation.json` 与 `.md` 已使用 `formal_eval_v1` hash `3b33876cd584e6215ef03a8bb07d0566aa57371957e606196c37b6f26641a4d9` 的冻结 test split 重跑；其他仍引用旧 hash 的报告继续按历史记录处理。

## Agentic 影子计划评测

`scripts/eval_agentic_shadow.py` 的 overlay 不调用 API、检索、工具或 LLM，也不会让 Planner/Router 接管正式主流程。它只衡量 shadow 意图、候选工具和有界计划是否符合人工预期，不能解释为最终问答准确率。
