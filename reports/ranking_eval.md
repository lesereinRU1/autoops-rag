# Ranking-only Evaluation

> 本报告是 ranking-only eval，只评估检索排序，不调用外部 LLM，不调用 `/api/chat`，不生成答案，也不代表最终生成质量。

- 运行模式：`api`
- 检索策略：`hybrid`
- Split：`development`
- 可回答题：35
- 跳过不可回答/危险题：5

## Metrics

| Metric | Value |
|---|---:|
| Strict Recall@5 | 1.0000 |
| MRR@5 | 0.9343 |
| nDCG@5 | 0.9377 |
| Top1 Accuracy | 0.8857 |
| Gold missing Top5 | 0 |
| Gold in Top5 but not Top1 | 4 |

## Gold missing Top5

无。

## Ranking late

### formal_004

- 问题：S7-1200 与 Modbus 通信不上时，应该按哪些层次排查？
- Gold：`["autoops_故障排查流程_3b38e4eccb_0001_0002"]`
- Top5：`["autoops_故障排查流程_3b38e4eccb_0001_0005", "autoops_故障排查流程_3b38e4eccb_0001_0003", "autoops_故障排查流程_3b38e4eccb_0001_0001", "autoops_故障排查流程_3b38e4eccb_0001_0004", "autoops_故障排查流程_3b38e4eccb_0001_0002"]`
- Gold rank：`{"autoops_故障排查流程_3b38e4eccb_0001_0002": 5}`
- 初判原因：`query_too_broad`

### formal_009

- 问题：现场把手册里的 40001 直接填进 Modbus TCP 报文地址后读数不对，应该先核对什么？
- Gold：`["autoops_modbus地址与数据检查_fbbb96bbd5_0001_0001"]`
- Top5：`["autoops_故障排查流程_3b38e4eccb_0001_0003", "autoops_modbus地址与数据检查_fbbb96bbd5_0001_0001", "autoops_中文操作与安全边界_a52df96344_0001_0001", "autoops_modbus地址与数据检查_fbbb96bbd5_0001_0003", "autoops_故障排查流程_3b38e4eccb_0001_0004"]`
- Gold rank：`{"autoops_modbus地址与数据检查_fbbb96bbd5_0001_0001": 2}`
- 初判原因：`ranking_late`

### formal_024

- 问题：PLC 和对端可以互相 ping 通，但 MB_CLIENT 仍然通信失败，下一步应检查什么？
- Gold：`["autoops_故障排查流程_3b38e4eccb_0001_0002"]`
- Top5：`["autoops_故障排查流程_3b38e4eccb_0001_0003", "autoops_故障排查流程_3b38e4eccb_0001_0002", "siemens_s7_1200_system_manual_v4_6_5513d52763_0945_8153", "siemens_s7_1200_system_manual_v4_6_5513d52763_1058_8882", "autoops_modbus地址与数据检查_fbbb96bbd5_0001_0004"]`
- Gold rank：`{"autoops_故障排查流程_3b38e4eccb_0001_0002": 2}`
- 初判原因：`chunk_text_too_similar`

### formal_027

- 问题：如何根据 STATUS 和现场现象区分通信伙伴超时与 CONNECT 连接描述错误，并安排排查顺序？
- Gold：`["autoops_故障排查流程_3b38e4eccb_0001_0004", "autoops_故障排查流程_3b38e4eccb_0001_0003", "autoops_故障排查流程_3b38e4eccb_0001_0002"]`
- Top5：`["autoops_故障排查流程_3b38e4eccb_0001_0005", "autoops_故障排查流程_3b38e4eccb_0001_0004", "autoops_故障排查流程_3b38e4eccb_0001_0001", "autoops_故障排查流程_3b38e4eccb_0001_0003", "autoops_故障排查流程_3b38e4eccb_0001_0002"]`
- Gold rank：`{"autoops_故障排查流程_3b38e4eccb_0001_0004": 2, "autoops_故障排查流程_3b38e4eccb_0001_0003": 4, "autoops_故障排查流程_3b38e4eccb_0001_0002": 5}`
- 初判原因：`query_too_broad`


## Scope

- 只读取人工预标注的 `gold_chunk_ids`，不会运行时生成 gold。
- 只调用 `/api/search` 或本地 `HybridRetriever`，不会调用外部 LLM。
- 本报告不修改检索排序权重、Prompt、安全拒答或正式评测集。
- ranking-only 指标不代表回答忠实度、拒答质量或最终生成质量。
