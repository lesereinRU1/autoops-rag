# Reports index

评测与审计报告分为“当前 canonical”与“Historical / stale / 历史版本结果”。不同 hash、split 和评测口径不能混用。

## 当前 canonical

- `formal_evaluation.json`：`formal_eval_v1` 当前 hash 的 test split 机器可读报告。
- `formal_evaluation.md`：与上述 JSON 对应的人类可读报告。

当前 dataset、corpus、Pytest、Planner 状态和指标总表见 `docs/current-status.md`。

## Historical / stale / 历史版本结果

除上述两个 canonical 文件外，本目录中的 ranking、旧 formal、agentic shadow、iterative、LLM smoke、benchmark、整改、验收、简历和演示材料均为历史或诊断材料。它们保留用于说明项目演进，不代表当前代码、当前 corpus 或当前正式评测结果。

特别注意：

- `ranking_eval.*`、`iterative_retrieval_eval.*` 等使用旧 dataset hash `e251df9e...`；
- `agentic_shadow_eval.*` 是 Stage G 前的 shadow-only 口径，不执行真实 Planner 工具；
- `formal_evaluation_development.md`、`formal_evaluation_test.md` 是新 E2E schema 前的历史报告；
- 旧简历、截图和验收材料可能包含 16,969 chunks、104 tests 等旧数字；
- 历史报告中的绝对路径已不再作为公开运行入口，当前公开启动方式以 repository root 为准。

历史报告不能用于宣传当前问答准确率或当前 Agent 能力。
