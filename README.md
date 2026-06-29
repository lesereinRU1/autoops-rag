# AutoOps RAG

用于检索S7-1200和Modbus技术手册，支持故障码、参数范围、普通问题和表格行查询。回答附带文档名称和页码。

## 使用范围

- 这是工业手册查询程序，不是通用编程Agent，不修改代码，也不执行PLC控制命令。
- 最近1到2轮问题只在短追问中用于补全参数名或操作对象，不会把完整聊天记录重新加入下一次查询。记录24小时有效，也可手动清空。
- 支持OpenAI Compatible外部模型。只有`.env`显式启用且证据充分时才调用；成功标记为`llm_grounded`，超时、接口错误、空响应或格式异常会记录原因并降级为本地证据摘录。
- 只有用户人工确认的处理方案会保存，并在相似问题中再次查询时作为参考。

## 项目内容

- 1785页官方资料生成16969个切片；其中12035个结构化表格行来自1861张表，保留版本、页码、表头、表号、行号、边界框和`chunk_id`。
- 检索时分别取得30条向量结果和30条BM25结果，使用RRF合并为20条，再选出5条。15题小规模回归集中，Dense Recall@5为60%，Hybrid为100%；但只有5题的正确证据来自官方手册，该子集MRR@10为56.67%、nDCG@10为67.50%，说明正确证据的排序仍需改进。
- LangGraph负责选择故障码查询、参数查询或手册检索。页面可记录反馈，人工确认后的方案可以在相似问题中再次使用。
- 最近1到2轮问题可用于处理`这个参数`、`那写入呢`一类追问，历史记录24小时有效并可手动清空。3组两轮测试全部通过，但样本数量还不足以代表开放对话。
- 新增20题应用层自查集，分开记录检索、必要事实、引用、工具选择和拒答。修改后事实字符串覆盖从36.67%升至96.67%，5道不可回答/危险问题拒答率从0升至100%；该数据集尚未独立审核，不能作为生产准确率。
- 查询改为并发读、索引重建独占写；完整问答超时为90秒、单次外部模型超时为40秒，并保留每分钟300次限流、请求编号和本地降级。既有12请求本地检索小样本中，8并发吞吐为4.668请求/秒、P95为2406.08毫秒；该数字不包含外部模型生成耗时。
- 切片审计中字符长度P95为1337，最大为6597，429个切片超过2000字符；按项目分词规则估算，超过600个词元的有4个。是否拆分检索文本需要经过同一评测集的对照测试后再决定。

技术栈：Python / FastAPI / LangGraph / Qdrant / BGE / BM25 / RRF / PyMuPDF / SQLite / Pytest

## 外部模型和RAG Trace

外部模型配置只保存在未提交的`.env`中，代码、日志和Trace均不写入API Key。必要变量为`LLM_ENABLED`、`LLM_BASE_URL`、`LLM_API_KEY`和`LLM_MODEL`，安全示例见`.env.example`。

每次`POST /api/chat`都会返回`request_id`和`rag_trace`，同时向`reports/rag_traces.jsonl`追加一行。Trace包含Dense、BM25、RRF候选、最终证据、注入上下文、模型、token、耗时、生成方式和降级原因。

- `GET /api/traces/{request_id}`：查询单次Trace。
- `GET /api/traces/recent?limit=20`：查询最近Trace。
- 页面中的“查看 RAG Trace”：查看本次检索和生成摘要。

## 启动

```powershell
Set-Location D:\autoops-rag
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\start_background.ps1
```

外部模型和Trace验收：

```powershell
.\.venv\Scripts\python.exe .\scripts\smoke_llm.py
```

- 页面：<http://127.0.0.1:8000>
- API：<http://127.0.0.1:8000/docs>
- 详细操作：[操作手册.md](操作手册.md)
- 向量库选型：[docs/ADR-001-vector-store-selection.md](docs/ADR-001-vector-store-selection.md)
- 表格抽取审计：[reports/table_extraction_audit.json](reports/table_extraction_audit.json)
- 切片长度审计：[reports/chunk_length_audit.json](reports/chunk_length_audit.json)
- 评测口径：[reports/评测方法说明.md](reports/评测方法说明.md)
- 应用层整改：[reports/应用层整改说明.md](reports/应用层整改说明.md)
- 应用层评测：[reports/application_evaluation.json](reports/application_evaluation.json)
- 索引一致性：[reports/index_reconciliation.json](reports/index_reconciliation.json)
- 多轮测试：[reports/memory_evaluation.json](reports/memory_evaluation.json)
- 运行耗时与并发：[reports/runtime_benchmark.json](reports/runtime_benchmark.json)
- 修改记录：[reports/V2升级说明.md](reports/V2升级说明.md)

限制：检索回归集只有15题，应用层自查集只有20题，均未经过独立盲审；应用层可回答题中只有5题来自官方手册。经典S7-1200 V4.6手册需要替换为V4.7。项目没有企业内部工单和真实生产成效数据；当前外部模型验收只证明调用、引用、token与Trace链路可工作，不能代表生产环境准确率。

安全边界：本项目不直接控制PLC。强制输出、旁路联锁、接线、下载程序或停送电必须由有资质人员按现场制度确认。
