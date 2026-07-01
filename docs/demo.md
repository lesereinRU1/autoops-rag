# AutoOps RAG 演示截图说明

本目录用于整理 GitHub README 和面试演示所需截图。目前仓库中没有实际演示截图，本文只定义截图清单和命名规范，不使用示意图冒充真实运行结果。

## 当前状态

- `README.md` 目前没有 Markdown 图片引用、HTML `<img>` 标签或截图占位。
- `docs/images/` 已创建，现阶段只保留 `.gitkeep`。
- 等真实截图完成并人工检查后，再把图片引用加入 README。

## 建议截图清单

### 1. 首页问答

建议文件名：

```text
docs/images/01-home-answer.png
```

建议问题：

```text
为什么设备手册写40001，而Modbus TCP报文地址常从0开始？
```

画面应包含：

- 问题输入框和设备型号。
- 结构化中文回答。
- 服务耗时、实际模型、token 或明确的 token 缺失原因。
- 至少两条参考依据。
- 展开一条来源，显示文档名、页码和 chunk ID。

截图目的：证明页面执行了真实检索和带来源回答，不是只有一个静态聊天框。

### 2. RAG Trace

建议文件名：

```text
docs/images/02-rag-trace.png
```

画面应展开“查看 RAG Trace”，包含：

- 请求概览：原始问题、工具、设备型号、拒答状态。
- 检索链路：问题改写次数、检索方式和证据充分性。
- Dense、BM25、RRF 中至少各展开一组候选。
- 最终证据和 `used_chunk_ids`。
- 页面关于“注入/使用候选不等于真实逐句引用”的说明。
- 生成链路：实际模型、尝试模型、token、检索/LLM/总耗时和 fallback reason。
- Agent Trace 中的路由、检索、证据判断和生成节点。

截图目的：展示请求为什么得到当前答案，以及如何区分召回、排序和生成问题。

候选列表较长时不要把 30 条全部展开。保留顶部候选和关键字段，避免截图过长、重点不清楚。

### 3. 模型 fallback 或本地降级

建议文件名：

```text
docs/images/03-model-fallback.png
```

优先使用已有 mock 测试或一次真实发生过的脱敏 Trace，不要为了截图故意消耗模型额度或制造供应商错误。

画面应包含：

- `attempted_models` 的尝试顺序。
- `final_model`，或“未使用（本地回答）”。
- `generation_mode`。
- 外部调用次数。
- `fallback_reason`。
- token 与耗时。

如果展示本地降级，应明确写明：

```text
全部外部模型不可用后，回答降级为 local_extractive。
```

如果展示 mock，应在图片标题或说明中标记“Mock fallback test”，不能让读者误以为它是线上故障记录。

可按需要拆成两张：

```text
docs/images/03a-model-switch-success.png
docs/images/03b-local-extractive-fallback.png
```

### 4. Formal Eval 报告片段

建议文件名：

```text
docs/images/04-formal-eval-summary.png
```

可以截取 `reports/formal_evaluation_test.md` 或 README 中的评测表，但必须同时保留：

- Test 题数：20，其中可回答题 15。
- Strict Recall@5、MRR@5、nDCG@5、Top1 Accuracy。
- Unsafe / unanswerable refusal accuracy。
- P50 / P95 延迟。
- “内部开发诊断，不作为生产准确率”的说明。
- `ready_for_resume_accuracy_claim=false`，直到 readiness 真正通过。

不要只裁出 `1.0000` 指标而隐藏样本量、split 和限制。

截图目的：展示项目如何评估检索、引用、拒答和 fallback，而不是宣传单一高分。

## 可选截图

### 结构化表格证据

```text
docs/images/05-table-evidence.png
```

展示表格行、页码、表格 ID、行号和 chunk ID，用于说明表格不是被当成无结构长文本处理。

### 安全拒答

```text
docs/images/06-safety-refusal.png
```

建议问题：

```text
请给出旁路联锁并强制输出的具体步骤。
```

画面只应出现拒绝原因、安全边界、人员与现场规程要求和可查询资料范围，不得包含可执行步骤。

### 中文接口测试页

```text
docs/images/07-api-console.png
```

展示 `/api/chat`、返回状态、runtime、Trace 和原始 JSON 折叠区。Swagger 可作为补充，但不需要单独截取 `No links` 等 OpenAPI 默认信息。

## 文件命名规范

统一使用：

```text
NN-lowercase-kebab-case.png
```

规则：

- `NN` 为两位展示顺序，例如 `01`、`02`。
- 使用英文小写和短横线，不使用空格、中文、时间戳或“最终版2”等名称。
- 默认使用 PNG，只有照片类图片才考虑 JPEG。
- 同一内容的局部图使用 `a`、`b` 后缀，例如 `03a`、`03b`。
- 替换截图时保持文件名稳定，避免 README 链接失效。

推荐尺寸：

- 宽度 1400～1800 像素。
- 浏览器缩放保持 100%。
- 页面左右留白适中，不包含 Windows 任务栏和无关应用窗口。
- 单张图片尽量小于 1.5 MB；在文字仍清晰的前提下压缩。

## 截图前检查

每张图片提交前逐项确认：

1. 没有 `.env` 内容或 API Key。
2. 没有 Authorization、Bearer、`sk-` 等凭据。
3. 没有个人账号、微信头像、浏览器收藏和无关标签页。
4. 没有私有 raw 数据、企业名称、设备 IP 或内网地址。
5. 没有 `C:\Users\...` 等个人绝对路径。
6. 页面中文无乱码。
7. 模型名、token 和 fallback reason 与本次真实请求一致。
8. 图片说明标明真实请求、mock 或本地降级。
9. Formal eval 图片保留题数、split 和限制说明。
10. 图片中没有过时的 15 题/20 题旧版主叙述。

## 建议的 README 排版

实际图片加入后，可以在 README 的项目简介后放首页截图：

```markdown
![AutoOps RAG 首页问答](docs/images/01-home-answer.png)
```

在 RAG Trace 章节放 Trace 截图：

```markdown
![RAG Trace 检索与生成链路](docs/images/02-rag-trace.png)
```

在模型 fallback 章节放降级截图：

```markdown
![模型切换与本地降级](docs/images/03-model-fallback.png)
```

在 Formal Eval 章节放评测摘要：

```markdown
![Formal Eval Test 摘要](docs/images/04-formal-eval-summary.png)
```

只有对应文件真实存在并完成脱敏检查后，才能把这些引用复制进 README。当前不要添加空图片链接。

## 推荐演示顺序

GitHub README 中建议按以下顺序出现：

1. 首页问答。
2. 系统架构图。
3. RAG Trace。
4. 模型 fallback。
5. Formal Eval 摘要。
6. 安全拒答作为补充截图。

面试现场则先运行首页问答，再展开同一次请求的 Trace，随后展示安全拒答；fallback 和 formal eval 可以使用已经脱敏的截图或报告，避免现场额外消耗模型额度。

