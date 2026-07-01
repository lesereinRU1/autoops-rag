# Formal Eval 60 题扩展计划

## 目标与边界

当前正式文件 `data/eval/formal_questions.jsonl` 保持 30 道 development 题不变。扩展草稿为 `data/eval/formal_questions_draft_041_070.jsonl`，其中包含 30 道待人工标注的题目骨架：新增 development 10 道、test 20 道。完成人工标注与复核后，正式目标是合计 60 道题，其中 development 40 道、test 20 道。

正式题 ID 不要求连续，只要求在正式文件与待合并草稿之间全局唯一。

草稿题不能用于正式 accuracy 宣传，也不能被当前正式评测、ranking-only eval 或简历指标自动计入。只有完成人工证据核对、gold 标注、required facts 拆分和复核状态升级后，才允许进入正式文件。

## 题型分布

| 方向 | 数量 | ID |
|---|---:|---|
| 地址表示 / 偏移换算 | 4 | `formal_041`–`formal_044` |
| 功能码 / 对象类型 | 4 | `formal_045`–`formal_048` |
| 长度 / 缓冲区 | 4 | `formal_049`–`formal_052` |
| 字节序 | 4 | `formal_053`–`formal_056` |
| 16#80C8 / 16#809A / 状态码 | 4 | `formal_057`–`formal_060` |
| 请求触发 / BUSY / 并发 | 3 | `formal_061`–`formal_063` |
| 信息不足 / 版本不匹配 | 3 | `formal_064`–`formal_066` |
| 危险请求 / 拒答 | 2 | `formal_067`–`formal_068` |
| 现场状态记录 / 分层排查 | 2 | `formal_069`–`formal_070` |

合计 30 题。可回答题 25 道，资料不足或版本不匹配题 3 道，危险拒答题 2 道。

## Development / Test 划分

- `formal_041`–`formal_050`：development，共 10 道。
- `formal_051`–`formal_070`：test，共 20 道。

test 题在完成双人复核前不得改为 `review_status=reviewed`，也不得用于最终指标。

## ID 去重状态

草稿已从 `formal_031`–`formal_060` 调整为 `formal_041`–`formal_070`，避开正式文件中已经占用的 `formal_031`–`formal_040`。当前正式题与草稿题 ID 无交集。

后续人工合并仍需执行全局唯一性检查，禁止覆盖正式文件中的同名题或静默合并。ID 可以不连续，但不得重复。

## 人工标注流程

1. 打开题目对应的公开手册或项目补充资料页面，确认问题确实可由当前资料回答。
2. 对 `answerable=true` 的题逐条选择直接支撑问题的 chunk，人工填写 `gold_chunk_ids`。不能使用当前检索 Top1、Top5 或生成答案自动反填 gold。
3. 将必答内容拆成短而单一的 `required_facts`，确保每条都能在至少一个人工 gold chunk 中直接找到支撑。
4. 填写必要的 `forbidden_facts`，尤其关注跨型号、跨版本、危险操作和证据外参数。
5. 核对 `source_scope`、设备型号、固件版本和手册版本；缺失信息不得用空泛结论代替。
6. 第一位标注人将 `review_status` 从 `draft` 改为 `self_checked`，填写 reviewer 和标注依据。
7. test 题由另一位复核人检查 question、gold、required facts 和拒答边界，确认后才可改为 `reviewed`。
8. 再次确认所有 ID 全局唯一后，手工选择性合并到正式 JSONL，再显式运行正式校验脚本。

## Gold 约束

- 禁止运行时生成 `gold_chunk_ids`。
- 禁止把检索 Top1、Top5 或 rerank 结果直接当作 gold。
- 禁止根据模型回答反推 gold。
- `answerable=true` 的草稿保持 `gold_chunk_ids=[]`、`required_facts=[]` 和 `gold_label_source=needs_human_label`，直到人工标注完成。
- `answerable=false` 的题使用 `gold_label_source=not_applicable`，并在 notes 中记录拒答或资料不足原因。

## 校验与评测隔离

`scripts/validate_formal_eval.py` 默认读取 `data/eval/formal_questions.jsonl`，因此不会自动计入本草稿。只有显式传入草稿路径时才会读取草稿；草稿的 `review_status=draft`、空 gold 和空 required facts 本来就不应通过正式 readiness 校验。

本轮不运行 `run_formal_eval.py`，不调用外部 LLM，也不修改检索、Prompt、LLM 或安全拒答逻辑。

## 宣传限制

这 30 道题只是候选骨架。它们没有人工 gold、没有 required facts、没有双人复核，不能用于 Recall、MRR、nDCG、Top1、claim support、refusal accuracy 或任何正式 accuracy 宣传。
