import type { WorkflowEvent } from "../types";

const stageLabels: Record<WorkflowEvent["stage"], string> = {
  request_started: "请求接收",
  analyzing: "意图与安全分析",
  tool_selected: "固定路由",
  retrieving: "混合检索",
  reranking: "融合与重排",
  rewriting: "有界改写",
  generating: "证据化生成",
  citation_check: "引用校验",
  completed: "完成",
  error: "错误",
};

export function WorkflowTimeline({ events }: { events: WorkflowEvent[] }) {
  return (
    <section className="panel workflow-panel">
      <div className="section-heading compact">
        <div>
          <span className="eyebrow">LIVE WORKFLOW</span>
          <h2>执行时间线</h2>
        </div>
        <span className="event-count">{events.length} events</span>
      </div>
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
