import type { ChatResponse } from "../types";

export function AnswerPanel({ response }: { response: ChatResponse | null }) {
  if (!response) {
    return (
      <section className="panel answer-panel">
        <span className="eyebrow">GROUNDED ANSWER</span>
        <h2>回答</h2>
        <p className="empty-state">最终回答会在 Citation Guard 完成后显示。</p>
      </section>
    );
  }

  const runtime = response.runtime;
  return (
    <section className="panel answer-panel">
      <div className="section-heading compact">
        <div>
          <span className="eyebrow">GROUNDED ANSWER</span>
          <h2>回答</h2>
        </div>
        <span className={response.evidence_sufficient ? "status-ok" : "status-warn"}>
          {response.evidence_sufficient ? "证据充分" : "证据不足 / 已拒答"}
        </span>
      </div>
      <div className="answer-copy">{response.answer}</div>
      <div className="metric-row">
        <span>总耗时 {runtime.total_ms.toFixed(2)} ms</span>
        <span>检索 {runtime.retrieval_latency_ms.toFixed(2)} ms</span>
        <span>生成 {runtime.llm_latency_ms.toFixed(2)} ms</span>
        <span>{runtime.final_model || "本地证据回答"}</span>
      </div>
      {response.warnings.length > 0 && (
        <div className="warning-box">{response.warnings.join("；")}</div>
      )}
    </section>
  );
}
