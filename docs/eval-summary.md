# 当前评测结果汇总

本页只汇总当前脚本和 `reports/` 中已有结果。不同评测回答不同问题，不能合并成一个“项目准确率”。

## 测试与数据校验

| 项目 | 当前结果 | 含义 |
|---|---:|---|
| Pytest | 115 passed | 单元、回归、安全、Agentic shadow、统一 Tool Registry、工具预算和迭代检索测试通过 |
| Formal questions | 60 | 50 道可回答题、10 道不可回答题，其中 4 道安全题 |
| Validation errors | 0 | schema、gold 来源和基本数据规则未发现错误 |
| Resume accuracy readiness | false | 官方资料占比和独立复核数量尚未达到宣传门槛 |

Readiness 未通过不是脚本失败：当前官方来源可回答题占比为 6%，`reviewed` 题为 20，低于策略要求的 70% 和 30 题。

## Ranking-only eval

数据：`formal_questions.jsonl` development split 中 35 道可回答题。脚本不调用 `/api/chat`、生成模型或 LLM judge。

| 指标 | 结果 |
|---|---:|
| Strict Recall@5 | 1.0000 |
| MRR@5 | 0.9343 |
| nDCG@5 | 0.9377 |
| Top1 Accuracy | 0.8857 |
| Gold missing Top5 | 0 |

指标含义：

- Strict Recall@5：每题全部人工 gold 是否都进入 Top5，再对题目取平均；
- MRR@5：第一个 gold 的倒数排名；
- nDCG@5：多个 gold 在 Top5 中的排序质量；
- Top1 Accuracy：第一条是否属于任一人工 gold。

这些指标只评价检索和排序，不评价生成答案是否完整、是否忠实，也不能证明现场可用率。

## Agentic shadow eval

数据：24 个 agentic overlay case，每类 intent 至少 3 条。评测不调用 API、检索、工具或 LLM，不执行 structured plan。

| 指标 | 结果 |
|---|---:|
| Intent Accuracy | 1.0000 |
| Tool Selection Accuracy | 1.0000 |
| Plan Valid Rate | 1.0000 |
| Safety Block Plan Accuracy | 1.0000 |
| Out-of-scope Block Plan Accuracy | 1.0000 |
| Budget Violation Count | 0 |
| Tool Whitelist Violation Count | 0 |
| Loop Violation Count | 0 |

这些 100% 表示规则分类、候选工具和 bounded plan 与小规模人工 overlay 预期一致。它不包含真实检索、工具执行和答案生成，绝不能写成“问答准确率 100%”。

## Iterative retrieval eval

数据：与 ranking-only 相同的 development answerable 集，并对不可回答/安全题执行策略回归检查。

| 指标 | 结果 |
|---|---:|
| Retry Trigger Rate before filtering | 0.0571（2/35） |
| Retry Trigger Rate after filtering | 0.0000（0/35） |
| Generic Term Retry Block Count | 2 |
| Unnecessary Retry Rate | 0.0000 |
| Strict Recall@5 legacy baseline | 0.9714 |
| Strict Recall@5 filtered candidate | 1.0000 |
| MRR@5 baseline → candidate | 0.9057 → 0.9343 |
| nDCG@5 baseline → candidate | 0.9132 → 0.9377 |
| Top1 baseline → candidate | 0.8286 → 0.8857 |
| Loop Violation Count | 0 |
| Safety Regression Count | 0 |
| Out-of-scope Regression Count | 0 |

两次旧触发分别由通用标识符 `0` 和 `PLC` 导致，阶段 7 过滤后均被阻断。这里的 candidate 收益包含“避免不必要 Rewrite 破坏原排序”，不表示二次检索本身一定提升召回。

当前过滤后没有 retry-positive case 真正执行第二轮，因此该实验能证明误触发下降，却不足以证明真实证据缺失时的二次检索收益。

## 不能作为最终问答准确率宣传的指标

- Ranking-only 的 Recall/MRR/nDCG/Top1；
- Agentic shadow 的 Intent/Tool/Plan 100%；
- 自动化测试通过率；
- Citation chunk valid rate；
- Iterative A/B 中避免 Rewrite 得到的检索增益。

要评价最终问答，还需要更高比例官方来源、独立复核 test 集，以及 claim support、required fact coverage、拒答正确性和人工抽检。当前 `ready_for_resume_accuracy_claim=false`，简历应写“在 35 题 development ranking-only 集上……”，不要写“系统准确率……”。

## 复现命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\validate_formal_eval.py
.\.venv\Scripts\python.exe scripts\eval_ranking_only.py --mode local --split development
.\.venv\Scripts\python.exe scripts\eval_agentic_shadow.py
.\.venv\Scripts\python.exe scripts\eval_iterative_retrieval.py
```
