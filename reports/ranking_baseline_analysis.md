# Ranking Baseline Analysis

> 本阶段只是 ranking baseline 分析，不是排序优化。报告没有调用外部 LLM，没有修改检索参数、评测集、gold 标签或 `reports/formal_evaluation.json`。

## 当前检索指标

统计范围为 25 道 `answerable=true` 的 development 题。

| 指标 | 当前值 |
|---|---:|
| Strict Recall@5 | 0.9200 |
| MRR@5 | 0.8880 |
| nDCG@5 | 0.9073 |
| Top1 Accuracy | 0.8000 |

`strict_recall@5` 对多 gold 题采用严格口径：全部人工 `gold_chunk_ids` 都进入 Top5 才记为命中。当前 23/25 道满足；20/25 道的 Top1 是 gold。

## 至少一个 gold 未进入 Top5

共 2 道。

### formal_027

- 问题：如何根据 STATUS 和现场现象区分通信伙伴超时与 CONNECT 连接描述错误，并安排排查顺序？
- Retrieval mode：`search_manual`
- 初判原因：`query_too_broad`
- Gold ranks：`0004 -> 2`，`0003 -> 4`，`0002 -> 5`，`安全边界_0002 -> 未进入Top5`
- Gold chunk IDs：
  - `autoops_故障排查流程_3b38e4eccb_0001_0004`
  - `autoops_故障排查流程_3b38e4eccb_0001_0003`
  - `autoops_故障排查流程_3b38e4eccb_0001_0002`
  - `autoops_中文操作与安全边界_a52df96344_0001_0002`
- Actual Top5：
  1. `autoops_故障排查流程_3b38e4eccb_0001_0005`
  2. `autoops_故障排查流程_3b38e4eccb_0001_0004`（gold）
  3. `autoops_故障排查流程_3b38e4eccb_0001_0001`
  4. `autoops_故障排查流程_3b38e4eccb_0001_0003`（gold）
  5. `autoops_故障排查流程_3b38e4eccb_0001_0002`（gold）
- 初判说明：问题同时包含两个 STATUS 场景和跨章节排查顺序。三个排障 gold 已召回，但安全边界 gold 被同主题的现场状态及请求触发 chunk 挤出。

### formal_028

- 问题：在把 Modbus 只读测试改为写寄存器请求之前，应完成哪些数据核对和安全边界确认？
- Retrieval mode：`search_manual`
- 初判原因：`gold_label_question_mismatch`
- Gold ranks：`故障流程_0003 -> 1`，`数据检查_0003 -> 2`，`数据检查_0004 -> 3`，`数据检查_0002 -> 4`，`故障流程_0005 -> 未进入Top5`
- Gold chunk IDs：
  - `autoops_故障排查流程_3b38e4eccb_0001_0003`
  - `autoops_modbus地址与数据检查_fbbb96bbd5_0001_0003`
  - `autoops_modbus地址与数据检查_fbbb96bbd5_0001_0004`
  - `autoops_modbus地址与数据检查_fbbb96bbd5_0001_0002`
  - `autoops_故障排查流程_3b38e4eccb_0001_0005`
- Actual Top5：
  1. `autoops_故障排查流程_3b38e4eccb_0001_0003`（gold）
  2. `autoops_modbus地址与数据检查_fbbb96bbd5_0001_0003`（gold）
  3. `autoops_modbus地址与数据检查_fbbb96bbd5_0001_0004`（gold）
  4. `autoops_modbus地址与数据检查_fbbb96bbd5_0001_0002`（gold）
  5. `autoops_中文操作与安全边界_a52df96344_0001_0002`
- 初判说明：缺失 gold 主要描述 BUSY、REQ 和并发排队，但本题必答事实集中在写入前数据核对与安全边界；实际第5名安全边界 chunk 与题意更直接。应先人工复核标签，不能直接据此调排序。

## 全部 gold 进入 Top5，但不是 Top1

共 4 道。

| Question ID | Gold rank | Retrieval mode | 初判原因 | 简要说明 |
|---|---:|---|---|---|
| `formal_001` | 2 | `search_manual` | `chunk_text_too_similar` | Top1 与 gold 来自同一地址与数据检查文档，但命中了字节序章节。 |
| `formal_004` | 5 | `search_manual` | `query_too_broad` | “通信不上、哪些层次”覆盖整份排障资料，同文档多个章节竞争。 |
| `formal_009` | 2 | `search_manual` | `ranking_late` | 地址表示 gold 已召回；现有报告没有分阶段分数，不能进一步归因。 |
| `formal_024` | 2 | `search_manual` | `chunk_text_too_similar` | Top1 与 gold 都描述通信失败排查，但一个偏未响应、一个偏分层检查。 |

### Top5 明细

#### formal_001

- 问题：为什么设备手册写40001，而Modbus TCP报文地址常从0开始？
- Gold：`autoops_modbus地址与数据检查_fbbb96bbd5_0001_0001`
- Actual Top5：`数据检查_0004`、`数据检查_0001 (gold)`、`故障流程_0003`、`安全边界_0001`、`故障流程_0002`

#### formal_004

- 问题：S7-1200 与 Modbus 通信不上时，应该按哪些层次排查？
- Gold：`autoops_故障排查流程_3b38e4eccb_0001_0002`
- Actual Top5：`故障流程_0005`、`故障流程_0003`、`故障流程_0001`、`故障流程_0004`、`故障流程_0002 (gold)`

#### formal_009

- 问题：现场把手册里的 40001 直接填进 Modbus TCP 报文地址后读数不对，应该先核对什么？
- Gold：`autoops_modbus地址与数据检查_fbbb96bbd5_0001_0001`
- Actual Top5：`故障流程_0003`、`数据检查_0001 (gold)`、`安全边界_0001`、`数据检查_0003`、`故障流程_0004`

#### formal_024

- 问题：PLC 和对端可以互相 ping 通，但 MB_CLIENT 仍然通信失败，下一步应检查什么？
- Gold：`autoops_故障排查流程_3b38e4eccb_0001_0002`
- Actual Top5：`故障流程_0003`、`故障流程_0002 (gold)`、`Siemens_0945_8153`、`Siemens_1058_8882`、`数据检查_0004`

完整 `chunk_id`、逐 gold rank 和 `is_gold` 标记见 [ranking_baseline_analysis.json](ranking_baseline_analysis.json)。

## 后续建议（本轮不实施）

1. 先人工复核 `formal_028` 的 gold 与 question、required facts 是否对齐，避免用标签问题驱动排序调整。
2. 对宽泛问题设计离线单变量实验，例如查询拆分或章节意图识别，但保持本报告作为固定 baseline。
3. 对相似 chunk 记录章节路径、标题命中和分阶段候选排名，先确认问题发生在召回还是融合后。
4. 对 `ranking_late` 样本补充只读的 Dense、BM25、RRF 分阶段诊断；缺少分阶段证据时不要直接改权重。
5. 后续每次只改变一个因素，同时比较 Strict Recall@5、MRR@5、nDCG@5 和 Top1 Accuracy。

## 限制

- 本分析没有运行时生成 gold，也没有修改任何 `gold_chunk_ids`。
- `formal_evaluation.json` 没有保存 Dense、BM25、RRF 各阶段排名与分数，因此“初判原因”不是因果结论。
- 本阶段只是 ranking baseline 分析，不是排序优化，也不能作为一次新的正式准确率评测。
