import type { ChatResponse } from "../types";

function value(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value, null, 2);
}

export function TracePanel({ response }: { response: ChatResponse | null }) {
  const trace = response?.rag_trace;
  const runtime = response?.runtime;
  const provider = trace?.generation_mode === "llm_grounded" ? "OpenAI-compatible" : "local";

  return (
    <details className="panel collapsible">
      <summary>
        <span>
          <span className="eyebrow">AUDIT TRACE</span>
          <strong>查看本次 Trace</strong>
        </span>
        <span>{trace?.request_id || "等待请求"}</span>
      </summary>
      {!trace || !runtime ? (
        <p className="empty-state">完整 Trace 会随 completed 事件一次性返回。</p>
      ) : (
        <div className="trace-content">
          <dl className="trace-grid">
            <dt>request_id</dt><dd>{trace.request_id}</dd>
            <dt>selected tool</dt><dd>{trace.selected_tool}</dd>
            <dt>rewritten query</dt><dd>{trace.rewritten_queries.join(" → ") || "未改写"}</dd>
            <dt>retry count</dt><dd>{trace.query_rewrite_attempts}</dd>
            <dt>stop reason</dt><dd>{trace.stop_reason || "—"}</dd>
            <dt>retrieval latency</dt><dd>{trace.retrieval_latency_ms.toFixed(2)} ms</dd>
            <dt>LLM latency</dt><dd>{trace.llm_latency_ms.toFixed(2)} ms</dd>
            <dt>total latency</dt><dd>{trace.total_latency_ms.toFixed(2)} ms</dd>
            <dt>model / provider</dt><dd>{trace.final_model || trace.llm_model || "local"} / {provider}</dd>
            <dt>token usage</dt>
            <dd>{trace.token_usage_available ? `${trace.total_tokens}（输入 ${trace.input_tokens} / 输出 ${trace.output_tokens}）` : `未返回：${trace.token_usage_missing_reason}`}</dd>
          </dl>
          <div className="trace-columns">
            <div>
              <h3>Tool calls</h3>
              <pre>{value(trace.tool_calls)}</pre>
            </div>
            <div>
              <h3>Retrieval rounds</h3>
              <pre>{value(trace.retrieval_rounds)}</pre>
            </div>
          </div>
        </div>
      )}
    </details>
  );
}
