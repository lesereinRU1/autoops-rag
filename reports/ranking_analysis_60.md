# v22 Ranking Analysis — 60 题 Formal Eval

> **Historical / stale / 历史版本结果。** 本文保留旧 ranking 诊断，当前 dataset/hash/指标见 `docs/current-status.md`。

> 本报告是 bad case 分析，不是排序优化结果。分析期间未修改业务代码、评测集、`gold_chunk_ids`、Prompt 或检索配置，也未调用外部 LLM。

## 1. 数据范围与口径

- 正式集：`data/eval/formal_questions.jsonl`，共 60 题。
- development：40 题，其中 35 道可回答题。
- test：20 题，其中 15 道可回答题。
- `reports/formal_evaluation.json` 当前是最后一次 test split 的副本，只包含 20 题明细。
- 为避免把 test 指标误写成 60 题指标，本报告同时读取已有的 `formal_evaluation_development.json` 与 `formal_evaluation_test.json`，按 item-level 明细和指标分母离线合并。没有重新运行 formal eval。
- 检索指标的 60 题合并值以 50 道可回答题为分母；required fact 指标以 289 条 required facts 为分母。不可回答题和危险题不进入检索指标分母。

## 2. 指标摘要

| 指标 | 60 题合并 | development | test |
|---|---:|---:|---:|
| `strict_recall@5` | 0.9400 | 0.9714 | 0.8667 |
| `mrr@5` | 0.9340 | 0.9057 | 1.0000 |
| `ndcg@5` | 0.9169 | 0.9132 | 0.9256 |
| `top1_accuracy` | 0.8800 | 0.8286 | 1.0000 |
| `required_fact_coverage` | 0.1557 | 0.1582 | 0.1518 |
| `required_fact_exact_coverage` | 0.1557 | 0.1582 | 0.1518 |
| `required_fact_diagnostic_coverage` | 0.4464 | 0.4633 | 0.4196 |
| `unanswerable_refusal_accuracy` | 1.0000 | 1.0000 | 1.0000 |
| `unsafe_refusal_accuracy` | 1.0000 | 1.0000 | 1.0000 |
| `fallback_success_rate` | 1.0000 | 1.0000 | 1.0000 |

合并 required fact 计数为：exact 45/289，diagnostic 129/289。合并指标用于本报告定位问题，不替代脚本原生输出的 split 指标。

## 3. `strict_recall@5 < 1` 清单

这里的 strict recall 是“该题所有 gold chunk 都进入 Top5”才记 1；只召回部分 gold 时整题记 0。因此它比“至少命中一个 gold”的口径严格。

| ID | Split | Top5 中 gold | 缺失 gold | Strict | MRR | nDCG | Top1 |
|---|---|---:|---|---:|---:|---:|---:|
| `formal_044` | development | 1/2 | `autoops_中文操作与安全边界_a52df96344_0001_0002` | 0 | 0.5000 | 0.3869 | 否 |
| `formal_057` | test | 2/3 | `autoops_故障排查流程_3b38e4eccb_0001_0004` | 0 | 1.0000 | 0.6714 | 是 |
| `formal_060` | test | 2/3 | `autoops_故障排查流程_3b38e4eccb_0001_0004` | 0 | 1.0000 | 0.7039 | 是 |

`formal_044` 的地址换算 gold 已在第 2 位，但 Top1 是同一检查清单中的“字节序”块，安全边界 gold 未进 Top5。该题同时包含“地址换算”和“安全边界”两个意图，既有同文档 chunk 文本相似导致的排序干扰，也应人工确认安全边界是否必须作为 strict gold，而不是只作为回答约束。

## 4. `formal_057` 详细分析

### 问题

STATUS 为 16#80C8 且故障偶发恢复时，应记录哪些现场量，并按什么范围继续排查？

### Gold chunks

1. `autoops_故障排查流程_3b38e4eccb_0001_0003`：16#80C8 含义及排查范围。
2. `autoops_故障排查流程_3b38e4eccb_0001_0001`：现场状态、版本、调用状态和通信参数记录。
3. `autoops_故障排查流程_3b38e4eccb_0001_0004`：16#809A 与 CONNECT 结构核对。

### 实际 Top5 evidence

| Rank | Chunk ID | 是否 gold | 内容概括 |
|---:|---|---:|---|
| 1 | `autoops_故障排查流程_3b38e4eccb_0001_0003` | 是 | 16#80C8 与通信伙伴未响应排查 |
| 2 | `siemens_s7_1200_system_manual_v4_6_5513d52763_0966_2181` | 否 | MB_RED_CLIENT、重试及 16#80C8 |
| 3 | `siemens_s7_1200_system_manual_v4_6_5513d52763_1057_2437` | 否 | MB_CLIENT 连接及协议错误表 |
| 4 | `autoops_故障排查流程_3b38e4eccb_0001_0001` | 是 | 现场状态记录 |
| 5 | `siemens_s7_1200_system_manual_v4_6_5513d52763_0943_2133` | 否 | MB_CLIENT 连接、超时和 Unit ID |

回答中出现了来源 1、2、3、4，均可映射到本次 evidence；缺失的 16#809A gold 没有被引用。

### 指标

- `strict_recall@5 = 0.0`
- `ndcg@5 = 0.6714`
- `top1_correct = true`
- gold 覆盖：2/3
- required fact exact：0/8
- required fact diagnostic：4/8

### 原因判断

主要原因不是 Top1 排序错误，而是多 gold 的严格全覆盖要求与题目范围不一致：题目只问 16#80C8，但 gold 和 required facts 又要求 16#809A/CONNECT 内容。检索把直接相关的 16#80C8 放在第 1 位、现场记录放在第 4 位，是合理结果；未召回 16#809A 更接近 **gold 标注/required facts 过宽**。

建议优先人工复核该题的 16#809A gold 和相关 required facts 是否属于直接必答证据。只有确认题目确实要求对比 16#809A 后，才考虑 query rewrite。当前证据不支持把它判定为 rerank 问题。

## 5. `formal_060` 详细分析

### 问题

同一程序先出现 16#809A、随后又出现 16#80C8 时，应怎样分别保存证据并安排检查顺序？

### Gold chunks

1. `autoops_故障排查流程_3b38e4eccb_0001_0001`：现场状态与诊断缓冲区记录。
2. `autoops_故障排查流程_3b38e4eccb_0001_0004`：16#809A 与 CONNECT 结构核对。
3. `autoops_故障排查流程_3b38e4eccb_0001_0003`：16#80C8 与通信伙伴未响应排查。

### 实际 Top5 evidence

| Rank | Chunk ID | 是否 gold | 内容概括 |
|---:|---|---:|---|
| 1 | `autoops_故障排查流程_3b38e4eccb_0001_0003` | 是 | 16#80C8 排查 |
| 2 | `autoops_modbus地址与数据检查_fbbb96bbd5_0001_0004` | 否 | 32 位数值字节序 |
| 3 | `autoops_故障排查流程_3b38e4eccb_0001_0001` | 是 | 现场状态记录 |
| 4 | `autoops_故障排查流程_3b38e4eccb_0001_0002` | 否 | 通信分层排查 |
| 5 | `siemens_s7_1200_system_manual_v4_6_5513d52763_0943_2133` | 否 | MB_CLIENT 连接、超时和 Unit ID |

回答引用了 evidence 的来源 1、2、3；其中来源 2 是与本题弱相关的字节序块。16#809A gold 未进入 Top5，也未被引用。

### 指标

- `strict_recall@5 = 0.0`
- `ndcg@5 = 0.7039`
- `top1_correct = true`
- gold 覆盖：2/3
- required fact exact：0/9
- required fact diagnostic：0/9

### 原因判断

该题明确同时包含 16#809A、16#80C8 和现场取证，三个 gold 与题意基本一致，因此不宜先删 gold。Top1 正确只说明至少一个 gold 排在首位，不能掩盖 16#809A 证据完全缺失。

初判是 **复合查询的召回覆盖不足/query rewrite 不足**：当前结果偏向 16#80C8，并混入字节序块，没有覆盖 16#809A 子意图。仅凭最终 Top5 无法断定是 retrieval miss 还是 ranking late；需要后续报告保留 Dense、BM25、RRF 候选及各自 rank。若 16#809A chunk 已在候选池但排在 Top5 外，才属于 rerank/ranking_late；若候选池也没有，则应先做双状态码子查询或 query rewrite，而不是调 rerank 权重。

## 6. Required fact coverage 分析

### 全局分类

| 诊断类型 | 60 题合并数量 | 说明 |
|---|---:|---|
| `exact_match` | 45 | 原始严格子串命中 |
| `semantic_match` / `checker_false_negative` | 84 | exact 未命中，但离线确定性语义检查认为已表达 |
| `missing_from_answer` | 99 | 当前回答未覆盖 |
| `required_fact_too_broad` | 25 | 单条 required fact 混合多个原子事实 |
| `required_fact_not_directly_supported_by_gold` | 36 | required fact 与 gold 证据不完全对齐 |

exact coverage 只有 15.57%，不能直接解释为模型仅答对 15.57%。84 条属于 exact checker 的同义表达漏判；同时仍有 99 条真实漏答候选、25 条复合标签和 36 条 gold 支持不足，需要分别处理。diagnostic coverage 44.64% 也只是离线诊断指标，不应作为正式准确率宣传。

### 低覆盖题

以下列出 diagnostic coverage 不高于 0.25 的题，报告已有 item-level 数据，因此可以直接定位，并非只能看到全局指标。

| ID | Split | Exact | Diagnostic | Facts | 主要诊断 |
|---|---|---:|---:|---:|---|
| `formal_004` | development | 0.0000 | 0.0000 | 4 | missing 4 |
| `formal_012` | development | 0.0000 | 0.0000 | 4 | missing 1，gold 支持不足 3 |
| `formal_024` | development | 0.0000 | 0.0000 | 3 | missing 2，gold 支持不足 1 |
| `formal_027` | development | 0.0000 | 0.0000 | 5 | missing 2，复合事实 2，gold 支持不足 1 |
| `formal_060` | test | 0.0000 | 0.0000 | 9 | missing 3，复合事实 6 |
| `formal_063` | test | 0.1111 | 0.1111 | 9 | missing 4，复合事实 4 |
| `formal_059` | test | 0.0000 | 0.1250 | 8 | missing 5，复合事实 2，checker 漏判 1 |
| `formal_051` | test | 0.1667 | 0.1667 | 6 | missing 4，gold 支持不足 1 |
| `formal_009` | development | 0.0000 | 0.2000 | 5 | missing 4，checker 漏判 1 |
| `formal_002` | development | 0.0000 | 0.2500 | 4 | missing 2，复合事实 1，checker 漏判 1 |
| `formal_011` | development | 0.0000 | 0.2500 | 4 | missing 1，复合事实 2，checker 漏判 1 |
| `formal_032` | development | 0.0000 | 0.2500 | 4 | missing/复合/gold 支持不足/checker 漏判各 1 |
| `formal_035` | development | 0.0000 | 0.2500 | 4 | gold 支持不足 3，checker 漏判 1 |
| `formal_038` | development | 0.0000 | 0.2500 | 4 | missing 2，gold 支持不足 1，checker 漏判 1 |
| `formal_047` | development | 0.2500 | 0.2500 | 8 | missing 2，gold 支持不足 4 |

`formal_057` 是很典型的口径差异：exact 为 0，但 diagnostic 为 0.5；`formal_060` 则 exact 和 diagnostic 都为 0，回答实际只集中在部分状态码和弱相关证据，属于更真实的覆盖问题。

## 7. 下一步建议（本轮不实施）

1. **先复核 gold，再调检索**：优先人工复核 `formal_044` 的安全边界 gold、`formal_057` 的 16#809A gold 是否属于问题直接核心。不要为了指标直接删除 gold，应同步核对 question 与 required facts。
2. **针对复合查询增强 query rewrite**：`formal_060` 可拆成“16#809A”“16#80C8”“现场证据记录”三个检索子意图，再融合结果。这里只是建议，本报告未修改实现。
3. **rerank 要有候选级证据再做**：评估输出应增加 Dense/BM25/RRF 的候选 chunk、原始 rank 和融合 rank。目标 gold 若根本没进候选池，rerank 无法解决；若进候选但落在 Top5 后，才标记 `ranking_late`。
4. **增加 item-level `missing_required_facts`**：JSON/Markdown 应直接列出每题 exact missing、diagnostic missing、too broad、gold-not-supported，避免再从 diagnostics 二次推导。
5. **拆分复合 required facts**：一条标签只表达一个可核验事实，保留原始 exact 口径，同时继续报告 diagnostic 口径；不能用 diagnostic 替代正式准确率。
6. **明确 answerable=false 分母**：当前检索指标实际只统计 50 道 answerable 题，拒答题另算 refusal accuracy。后续报告应直接显示该分母，避免把 60 题总数误当检索分母。
7. **保存 split 与合并报告**：当前脚本已留下 development/test 文件，但 `formal_evaluation.json` 会被最后一次运行覆盖。建议增加离线汇总报告，防止把 test 20 题指标误称为全 60 题指标。

## 8. 结论

- 60 题中 50 道可回答题的合并 `strict_recall@5` 为 0.9400，只有 3 题未实现全部 gold 的 Top5 覆盖。
- `formal_057` 的 Top1 和 MRR 均正确，核心问题更像题目只问 16#80C8、但 gold/required facts 扩展到 16#809A。
- `formal_060` 的 gold 与题意匹配，缺失 16#809A chunk，优先调查复合 query 的子意图召回；在没有候选 rank 前不应直接归因 rerank。
- required fact 偏低同时包含 checker 过严、真实漏答、复合标签和 gold 不对齐，不能只靠调排序解决。
