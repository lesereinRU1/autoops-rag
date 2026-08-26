# Gold Label Fix 后的 Ranking Baseline

> **Historical / stale / 历史版本结果。** 本报告不是当前 canonical evaluation，不能作为当前检索或回答指标。

> 本报告是修正 `formal_027`、`formal_028` 人工 gold 标注后的 ranking baseline，不是排序优化。本轮没有运行检索、调用外部 LLM，或修改检索代码、Prompt 和 gold。

## 当前检索指标

统计范围为 25 道 `answerable=true` 的 development 题。

| 指标 | Gold fix 后 |
|---|---:|
| Strict Recall@5 | 1.0000 |
| MRR@5 | 0.8880 |
| nDCG@5 | 0.9171 |
| Top1 Accuracy | 0.8000 |

- 全部 gold 进入 Top5：25/25
- Top1 为 gold：20/25
- 至少一个 gold 未进入 Top5：0 题
- 全部 gold 进入 Top5 但不是 Top1：5 题

## Gold label fix 的影响

### formal_027

移除非核心的安全边界 gold 后，三个 gold 分别位于 Top2、Top4、Top5。该题不再属于 Top5 缺失，现归类为 `ranking_late / query_too_broad`。

### formal_028

用与题目安全边界更直接对齐的 chunk 替换并发触发 chunk 后，五个 gold 分别位于 Top1、Top2、Top3、Top4、Top5；该题 Strict Recall@5 和 Top1 均命中，不再是排序异常题。

## Gold 未进入 Top5

当前为 **0 题**。

## Gold 进入 Top5 但不是 Top1

| Question ID | Gold rank | 初判原因 | 说明 |
|---|---:|---|---|
| `formal_001` | 2 | `chunk_text_too_similar` | 同一地址与数据检查文档中，字节序章节排在地址表示章节之前。 |
| `formal_004` | 5 | `query_too_broad` | 宽泛排障问题使同文档多个排障章节共同竞争。 |
| `formal_009` | 2 | `ranking_late` | 地址表示 gold 已召回，但当前报告没有分阶段排名可进一步归因。 |
| `formal_024` | 2 | `chunk_text_too_similar` | 通信伙伴未响应与分层排查 chunk 语义接近。 |
| `formal_027` | 2、4、5 | `query_too_broad` | 同时包含两个 STATUS 场景和跨章节排查顺序。 |

### formal_001

- 问题：为什么设备手册写40001，而Modbus TCP报文地址常从0开始？
- Gold：`autoops_modbus地址与数据检查_fbbb96bbd5_0001_0001`，rank=2
- Actual Top5：`数据检查_0004`、`数据检查_0001 (gold)`、`故障流程_0003`、`安全边界_0001`、`故障流程_0002`

### formal_004

- 问题：S7-1200 与 Modbus 通信不上时，应该按哪些层次排查？
- Gold：`autoops_故障排查流程_3b38e4eccb_0001_0002`，rank=5
- Actual Top5：`故障流程_0005`、`故障流程_0003`、`故障流程_0001`、`故障流程_0004`、`故障流程_0002 (gold)`

### formal_009

- 问题：现场把手册里的 40001 直接填进 Modbus TCP 报文地址后读数不对，应该先核对什么？
- Gold：`autoops_modbus地址与数据检查_fbbb96bbd5_0001_0001`，rank=2
- Actual Top5：`故障流程_0003`、`数据检查_0001 (gold)`、`安全边界_0001`、`数据检查_0003`、`故障流程_0004`

### formal_024

- 问题：PLC 和对端可以互相 ping 通，但 MB_CLIENT 仍然通信失败，下一步应检查什么？
- Gold：`autoops_故障排查流程_3b38e4eccb_0001_0002`，rank=2
- Actual Top5：`故障流程_0003`、`故障流程_0002 (gold)`、`Siemens_0945_8153`、`Siemens_1058_8882`、`数据检查_0004`

### formal_027

- 问题：如何根据 STATUS 和现场现象区分通信伙伴超时与 CONNECT 连接描述错误，并安排排查顺序？
- Gold：
  - `autoops_故障排查流程_3b38e4eccb_0001_0004`，rank=2
  - `autoops_故障排查流程_3b38e4eccb_0001_0003`，rank=4
  - `autoops_故障排查流程_3b38e4eccb_0001_0002`，rank=5
- Actual Top5：`故障流程_0005`、`故障流程_0004 (gold)`、`故障流程_0001`、`故障流程_0003 (gold)`、`故障流程_0002 (gold)`

完整 `chunk_id`、Top5 顺序和 `is_gold` 标记见 [ranking_baseline_analysis.json](ranking_baseline_analysis.json)。

## 限制

- 本报告是 gold label fix 后的 ranking baseline，不是排序优化。
- 指标使用最新 formal report 中已存在的 Top5 和当前人工 gold 离线核对，没有发起检索或生成请求。
- 没有修改 `reports/formal_evaluation.json`。
- formal report 没有保存 Dense、BM25、RRF 各阶段排名与分数，因此原因分类不是因果结论。
