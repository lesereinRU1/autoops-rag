import type { ChatResponse, Plan } from "../types";

function value(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value, null, 2);
}

export function TracePanel({ response }: { response: ChatResponse | null }) {
  const trace = response?.rag_trace;
  const runtime = response?.runtime;
  const plan = trace?.plan && !Array.isArray(trace.plan) && "steps" in trace.plan
    ? (trace.plan as Plan)
    : null;
  const citation = response?.agent_trace.find((item) => item.node === "citation_guard");
  const plannerStatus = trace?.planner_fallback
    ? "fallback"
    : trace?.planner_applied
      ? "applied"
      : trace?.planner_attempted
        ? "attempted"
        : "skipped";

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
            <dt>planner</dt><dd>{plannerStatus}</dd>
            <dt>planner fallback</dt><dd>{trace.planner_fallback_reason || "—"}</dd>
            <dt>selected tool</dt><dd>{trace.selected_tool}</dd>
            <dt>rewritten query</dt><dd>{trace.rewritten_queries.join(" → ") || "未改写"}</dd>
            <dt>retry count</dt><dd>{trace.query_rewrite_attempts}</dd>
            <dt>stop reason</dt><dd>{trace.stop_reason || "—"}</dd>
            <dt>retrieval latency</dt><dd>{trace.retrieval_latency_ms.toFixed(2)} ms</dd>
            <dt>LLM latency</dt><dd>{trace.llm_latency_ms.toFixed(2)} ms</dd>
            <dt>total latency</dt><dd>{trace.total_latency_ms.toFixed(2)} ms</dd>
            <dt>model / mode</dt><dd>{trace.final_model || trace.llm_model || "local"} / {trace.generation_mode}</dd>
            <dt>citation guard</dt><dd>{citation ? `${String(citation.action)} / valid=${String(citation.valid)}` : "未执行"}</dd>
            <dt>token usage</dt>
            <dd>{trace.token_usage_available ? `${trace.total_tokens}（输入 ${trace.input_tokens} / 输出 ${trace.output_tokens}）` : `未返回：${trace.token_usage_missing_reason}`}</dd>
          </dl>
          <div className="trace-section">
            <div className="trace-section-heading">
              <h3>Plan</h3>
              <span>{plan ? `${plan.steps.length} step(s)` : "无执行计划"}</span>
            </div>
            {plan ? (
              <div className="plan-stack">
                {plan.steps.map((step) => (
                  <article className="plan-step" key={step.step_id}>
                    <div><span>{step.step_id}</span><strong>{step.tool_name}</strong></div>
                    <p>{step.reason}</p>
                    <small>expected: {step.expected_evidence}</small>
                    <pre>{value(step.arguments)}</pre>
                  </article>
                ))}
              </div>
            ) : <p className="empty-state">稳定规则或 Safety/Scope 路径没有应用 Planner plan。</p>}
          </div>
          <div className="trace-section">
            <div className="trace-section-heading">
              <h3>Budget snapshot</h3>
              <span>request-scoped</span>
            </div>
            <dl className="budget-grid">
              {Object.entries(trace.budget).map(([key, item]) => (
                <div key={key}><dt>{key}</dt><dd>{value(item)}</dd></div>
              ))}
            </dl>
          </div>
          <div className="trace-section">
            <div className="trace-section-heading">
              <h3>Tool calls</h3>
              <span>{trace.tool_calls.length} record(s)</span>
            </div>
            {trace.tool_calls.length === 0 ? <p className="empty-state">本次没有工具调用记录。</p> : (
              <div className="tool-call-list">
                {trace.tool_calls.map((call, index) => (
                  <article className="tool-call-row" key={`${call.tool_name ?? "tool"}-${index}`}>
                    <div className="tool-call-title">
                      <strong>{call.tool_name ?? "unknown tool"}</strong>
                      <span className={call.success ? "status-ok" : "status-warn"}>{call.success ? "success" : call.error || "failed"}</span>
                    </div>
                    <div className="tool-call-flags">
                      <span>executed={String(call.executed ?? false)}</span>
                      <span>reused={String(call.reused ?? false)}</span>
                      <span>deduplicated={String(call.deduplicated ?? false)}</span>
                      <span>count={call.result_count ?? 0}</span>
                      <span>{(call.latency_ms ?? 0).toFixed(2)} ms</span>
                    </div>
                    <details>
                      <summary>arguments / remaining budget</summary>
                      <pre>{value({ arguments: call.arguments, remaining_budget: call.remaining_budget })}</pre>
                    </details>
                  </article>
                ))}
              </div>
            )}
          </div>
          <div className="trace-columns">
            <div>
              <h3>Evidence Gate</h3>
              <pre>{value(trace.evidence_assessments)}</pre>
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
