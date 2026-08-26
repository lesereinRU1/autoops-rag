# LLM与RAG Trace整改说明

> **Historical / stale / 历史版本材料。** 本文保留用于说明历史整改过程，不代表当前代码、测试或 canonical evaluation；当前事实见 `docs/current-status.md`。

## 本次修改

- 外部模型成功时统一记录`llm_grounded`；禁用、超时、接口错误、空响应和格式异常时降级为`local_extractive`并记录明确原因。
- 当前使用非流式OpenAI Compatible请求，读取响应`usage`中的输入、输出和总token。供应商未返回或字段无法解析时保留空值并写明原因，不估算token。
- 回答固定为结论、原因、排查/换算建议、引用来源和安全提示五部分。模型只能使用注入证据，引用来源清单由程序按实际使用的来源和`chunk_id`整理。
- 每次`/api/chat`把Dense、BM25、RRF、最终证据、注入上下文、模型、token、耗时、降级原因和拒答状态写入`reports/rag_traces.jsonl`。
- 增加单次Trace和最近Trace接口，项目页与接口测试页均可展开查看本次Trace。
- 完整问答超时为90秒，单次外部模型超时为40秒。百炼请求采用直连，避免本机系统代理在TLS握手阶段返回EOF。

## 接口

- `POST /api/chat`
- `GET /api/traces/{request_id}`
- `GET /api/traces/recent?limit=20`

## 验证结果

2026-06-29在本机使用`qwen-plus`完成指定地址问题验收：

- `generation_mode=llm_grounded`
- 外部模型调用1次
- 输入token 1408，输出token 439，总token 1847
- Dense 30条、BM25 30条、RRF 20条、最终证据5条
- `request_id=f48088e2879a4202a7c437cf4c38a515`
- 两个安全/范围拒答用例均未调用外部模型
- Pytest共18项通过

以上token和耗时是单次调用记录，不代表生产平均值。API Key只保存在未提交的`.env`中；代码和Trace已按当前配置值做过泄漏检查。

## 复测命令

```powershell
Set-Location <repository-root>
.\scripts\start_background.ps1
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe .\scripts\smoke_llm.py
```
