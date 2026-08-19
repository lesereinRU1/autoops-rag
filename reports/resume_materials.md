# AutoOps RAG 简历与面试材料

> 建议项目标题：AutoOps RAG——工业设备手册检索与故障辅助系统
>
> 项目角色：个人项目｜独立开发者

## A. 项目一句话描述

基于 LangGraph 构建面向 Siemens S7-1200 与 Modbus 技术资料的轻量级 Agentic RAG 系统，通过结构化文档解析、Dense + BM25 + RRF 混合检索、Evidence Gate、Citation Guard 和全链路 Trace，提供带页码与来源证据的参数查询和故障辅助分析。

## B. 1 分钟面试讲解

这个项目解决的是工业设备手册难检索、表格参数容易被切散，以及大模型可能在证据不足时补全答案的问题。

我先用 PyMuPDF 解析手册正文和表格，当前审计报告记录了 16,969 个知识切片，其中 12,035 个是表格行，覆盖 1,861 张表；每个切片保留页码、章节、型号、版本和表格元数据。检索层不是只用向量，而是组合 BGE/Qdrant、BM25、RRF 和轻量重排，兼顾自然语言和故障码、参数名等精确标识。在 35 道 development ranking-only 题上，Strict Recall@5 为 1.0，MRR@5 为 0.9343。

编排层用 LangGraph 显式拆分安全门控、工具查询、混合检索、Evidence Gate、Query Rewrite、回答生成和 Citation Guard。Agentic 扩展采用规则式 Intent Classifier、shadow Tool Router 和 bounded Planner，不让 Planner 直接接管生产路径；可选迭代检索默认关闭，并通过轮数、工具、LLM、Rewrite 和超时预算避免无限循环。FastAPI、Docker、Pytest 和独立 eval 脚本负责工程化与回归验证。

## C. 3 分钟面试讲解

### 1. 问题与数据

项目面向 Siemens S7-1200 和 Modbus 技术资料。这个场景有三个特点：第一，手册正文长、表格多，参数名和数值经常跨表头与行；第二，问题同时包含自然语言和 `MB_CLIENT`、`16#80C8`、端口 `502` 等精确标识；第三，工业场景不能允许模型在证据不足时自由补全，更不能输出旁路联锁等危险操作。

我用 PyMuPDF 构建页级正文和表格行两类表示，保留 `chunk_id`、页码、章节、型号、版本、`table_id`、表头和行号。当前审计报告中有 16,969 个切片，其中 12,035 个表格行来自 1,861 张表。

### 2. 检索与证据

只使用 Dense Retrieval 对语义问题有效，但容易漏掉故障码和参数名；只用 BM25 又不能覆盖自然语言改写。因此检索链采用 BGE/Qdrant Dense + BM25，使用 RRF 融合，再做轻量重排。

生成前设置 Evidence Gate，检查证据数量、相关度和技术标识符覆盖。阶段 7 又把原始缺失词拆成有效标识符和泛词，`0`、`PLC`、手册、参数等不能单独触发重试，而 `MB_CLIENT`、`16#80C8`、`ID`、`IP`、`502` 会保留。生成后 Citation Guard 校验来源是否属于本次 evidence，失败时降级成本地证据摘要。

当前 35 题 development ranking-only 结果为 Strict Recall@5 1.0000、MRR@5 0.9343、nDCG@5 0.9377、Top1 Accuracy 0.8857。这些只是检索指标，我不会把它们描述成最终问答准确率。

### 3. 工作流与 Agentic 设计

LangGraph 把流程拆成请求分析、安全短路、结构化工具、混合检索、Evidence Gate、Rewrite、生成和 Citation Guard，各节点状态和条件边都能测试与回滚。

在此基础上，我增加了规则式 Intent Classifier、候选 Tool Router 和 Bounded Query Planner。Planner 只允许白名单工具、最多 3 步，安全和越界意图不产生执行计划。它们目前主要 shadow 运行，计划写入 Trace 但 `applied=false`，避免分类器或 Planner 的早期误判直接改变稳定主流程。

Evidence-driven Iterative Retrieval 也是 gated experiment，默认关闭。只有证据不足、存在有效缺失标识、并且 `max_rounds`、`max_rewrites`、`max_tool_calls` 和 timeout 都允许时才补充一轮检索。评测中旧规则会被 `0` 和 `PLC` 触发两次无效重试，过滤后 Retry Trigger Rate 从 5.71% 降为 0，Loop/Safety/Out-of-scope Regression 都为 0。

### 4. 工程化和边界

服务使用 FastAPI，支持 Docker Compose、模型 fallback、限流、读写控制和请求级 Trace。SQLite 工具统一返回 `ToolResult`，SQL 使用参数化查询；没有来源信息的结构化结果不能直接当最终事实。

当前有 104 项 Pytest；formal 数据共 60 题且 0 validation errors。但官方资料占比和独立复核量尚未达到 readiness 门槛，所以项目适合描述为“完成可复现的工程实验和内部评测”，不能声称已经生产落地或达到生产准确率。

## D. 简历 Bullet（4 条）

1. **文档结构化：** 基于 PyMuPDF 解析工业技术资料，构建页级正文与表格行双表示；审计得到 16,969 个知识切片，其中 12,035 个表格行覆盖 1,861 张表，保留页码、章节、型号、版本、表头、行号及 `chunk_id` 等元数据。

2. **混合检索与评测：** 实现 BGE/Qdrant Dense Retrieval、BM25、RRF 融合与轻量重排；建立人工预标注 gold 的 ranking-only 流程，在 35 道 development 题上取得 Strict Recall@5 1.0000、MRR@5 0.9343、nDCG@5 0.9377、Top1 Accuracy 0.8857。

3. **LangGraph / Agentic RAG：** 使用 LangGraph 构建可审计状态机，拆分安全门控、结构化工具、混合检索、Evidence Gate、Query Rewrite、生成和 Citation Guard；增加规则式 Intent Classifier、shadow Tool Router 与 Bounded Planner，通过白名单和预算控制形成轻量级 Agentic RAG，而非开放式无限循环 Agent。

4. **工程闭环：** 基于 FastAPI、SQLite、Docker Compose 和 Pytest 完成服务化、只读参数化工具、模型 fallback、限流与 Trace；记录 evidence assessment、检索轮次、引用、预算及 stop reason，建立 104 项测试和 ranking/shadow/iterative 三套隔离评测脚本。

## E. 面试追问回答

### 你的项目和普通 RAG 有什么区别？

普通 RAG 往往是一次向量检索后直接生成。我的项目增加了正文/表格双表示、Dense + BM25 + RRF、生成前 Evidence Gate、生成后 Citation Guard、安全短路、结构化 SQLite 工具和请求级 Trace。检索、证据判断、生成和引用失败都能分别定位。

### 你的项目算 Agentic RAG 吗？

算轻量级、受约束的 Agentic RAG，不是完全自主 Agent。系统能识别 intent、生成候选工具计划、评估证据并在预算内决定是否补充检索；但 Router/Planner 当前主要 shadow 运行，真实路由仍由固定 LangGraph 控制。

### 为什么 Planner 先做 shadow，而不是直接接管？

工业知识问答的错误路由可能导致错版本或错参数进入答案。先 shadow 可以在不影响稳定 API 的情况下积累 intent、tool selection、budget 和 plan valid 指标，发现误判后再决定是否灰度接管。这样每阶段能独立测试和回滚。

### Evidence Gate 怎么判断证据不足？

它使用规则检查 evidence 是否存在、Top score 是否过低，以及问题中的技术标识符是否被证据覆盖。标识符分为 raw missing、filtered missing 和 ignored generic terms；只有 `MB_CLIENT`、故障码、端口等有区分度标识缺失时才可能触发 iterative retry，`0`、`PLC` 等泛词不会单独触发。

### 为什么 SQLite 工具结果不能直接当最终事实？

SQLite 记录可能是缓存、人工录入或缺少版本与页码。如果不能映射到可信 `source/page/chunk_id`，就无法通过 Citation Guard，也不能证明适用于当前设备版本。因此工具结果只能作为候选上下文，最终事实要回到可引用手册证据。

### 怎么防止 Agent 无限循环？

Planner 最多 3 步且只允许白名单工具；迭代检索默认关闭，开启后受 `max_agent_rounds=2`、`max_tool_calls=4`、`max_llm_calls=2`、`max_rewrites=1` 和 60 秒 timeout 限制。每轮更新 budget，并用明确 stop reason 结束。

### 你的 eval 指标分别说明什么？

Recall@5 说明全部 gold 是否进入 Top5；MRR 看首个 gold 排名；nDCG 看多个 gold 的整体排序；Top1 看第一条是否命中。Shadow eval 评价 intent、候选工具和计划约束。Iterative eval 评价 retry 触发、误触发、预算和安全回归。它们不能互相替代。

### Shadow eval 100% 能不能代表问答准确率？

不能。它只有 24 个 overlay case，不调用真实检索、工具和 LLM，只说明规则输出符合该 overlay 的人工预期。最终问答还受文档覆盖、检索、重排、证据和生成影响。

### 当前项目还有哪些不足？

Formal 集只有 60 题，官方来源可回答题占比 6%，独立复核题为 20，readiness 尚未通过；资料集中于 S7-1200/Modbus；iterative 校准后 development 集没有 retry-positive case；没有企业内部工单和真实生产效果数据；自动引用有效也不能替代 claim-level 人工复核。

## 使用口径

推荐写“个人项目 / 独立开发”“在 35 道 development ranking-only 题上取得……”“shadow overlay 中计划有效率为……”。

避免写“生产级”“企业落地”“问答准确率 100%”“Agent 自主完成故障诊断”“已减少现场停机时间”。这些结论当前没有数据支持。

