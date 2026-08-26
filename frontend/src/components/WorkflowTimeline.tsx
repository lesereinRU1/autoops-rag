import type { ChatResponse, WorkflowEvent } from "../types";

const stageLabels: Record<WorkflowEvent["stage"], string> = {
  request_started: "请求接收",
  analyzing: "意图与安全分析",
  tool_selected: "路由 / 工具选择",
  retrieving: "混合检索",
  reranking: "融合与重排",
  rewriting: "有界改写",
  generating: "证据化生成",
  citation_check: "引用校验",
  completed: "完成",
  error: "错误",
};

function traceNode(response: ChatResponse, node: string): Record<string, unknown> | undefined {
  return response.agent_trace.find((item) => item.node === node);
}

function plannerSummary(response: ChatResponse): { label: string; detail: string; tone: string } {
  const trace = response.rag_trace;
  if (trace.planner_fallback) {
    return {
      label: "Planner fallback",
      detail: trace.planner_fallback_reason || "已回退固定流程",
      tone: "warn",
    };
  }
  if (trace.planner_applied) {
    return {
      label: "Planner applied",
      detail: `round ${trace.planner_round} · 计划已真实执行`,
      tone: "ok",
    };
  }
  if (trace.planner_attempted) {
    return { label: "Planner attempted", detail: "已尝试但未应用", tone: "warn" };
  }
  return {
    label: "Planner skipped",
    detail: "feature flag 关闭或请求由稳定规则优先处理",
    tone: "neutral",
  };
}

function AuditSummary({ response }: { response: ChatResponse }) {
  const trace = response.rag_trace;
  const planner = plannerSummary(response);
  const assessment = trace.evidence_assessments.at(-1);
  const citation = traceNode(response, "citation_guard");
  const citationDetail = citation
    ? `${citation.valid ? "valid" : "invalid"} · ${String(citation.action ?? "unknown")}`
    : "Safety/Scope 路径未执行";
  const steps = [
    { label: planner.label, detail: planner.detail, tone: planner.tone },
    { label: "Tool selected", detail: trace.selected_tool || response.selected_tool, tone: "neutral" },
    { label: "Retrieval", detail: `${trace.retrieval_rounds.length} round(s)`, tone: trace.retrieval_rounds.length ? "ok" : "neutral" },
    { label: "Rewrite", detail: trace.rewrite_triggered ? trace.rewritten_queries.join(" → ") : "未触发", tone: trace.rewrite_triggered ? "warn" : "neutral" },
    {
      label: "Evidence Gate",
      detail: assessment
        ? `${assessment.sufficient ? "passed" : "insufficient"} · ${String(assessment.stop_reason ?? assessment.reason ?? "")}`
        : "Safety/Scope 路径未执行",
      tone: response.evidence_sufficient ? "ok" : "warn",
    },
    { label: "Generation", detail: response.runtime.generation_mode || "unknown", tone: "neutral" },
    { label: "Citation Guard", detail: citationDetail, tone: citation?.valid === false ? "warn" : "ok" },
    { label: "Completed", detail: trace.stop_reason || "completed", tone: "ok" },
  ];

  return (
    <div className="audit-summary">
      <div className="audit-heading">
        <strong>Trace 结算链路</strong>
        <small>来自 completed response，不是模拟事件</small>
      </div>
      <ol className="audit-steps">
        {steps.map((step) => (
          <li key={step.label} className={`audit-step tone-${step.tone}`}>
            <strong>{step.label}</strong>
            <span>{step.detail}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function WorkflowTimeline({
  events,
  response,
}: {
  events: WorkflowEvent[];
  response: ChatResponse | null;
}) {
  return (
    <section className="panel workflow-panel">
      <div className="section-heading compact">
        <div>
          <span className="eyebrow">LIVE WORKFLOW</span>
          <h2>执行时间线</h2>
        </div>
        <span className="event-count">{events.length} events</span>
      </div>
      {response && <AuditSummary response={response} />}
      {events.length === 0 ? (
        <p className="empty-state">提交问题后，这里会显示真实 LangGraph 阶段事件。</p>
      ) : (
        <ol className="timeline">
          {events.map((event, index) => (
            <li className={`timeline-item stage-${event.stage}`} key={`${event.timestamp}-${index}`}>
              <span className="timeline-dot" aria-hidden="true" />
              <div>
                <div className="timeline-title">
                  <strong>{stageLabels[event.stage]}</strong>
                  <time>{new Date(event.timestamp).toLocaleTimeString()}</time>
                </div>
                <p>{event.message}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
