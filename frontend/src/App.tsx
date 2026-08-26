import { useRef, useState } from "react";

import { streamChat } from "./api/client";
import { AnswerPanel } from "./components/AnswerPanel";
import { ChatForm, type ChatFormValue } from "./components/ChatForm";
import { CitationPanel } from "./components/CitationPanel";
import { EvidencePanel } from "./components/EvidencePanel";
import { TracePanel } from "./components/TracePanel";
import { WorkflowTimeline } from "./components/WorkflowTimeline";
import type { ChatRequest, ChatResponse, WorkflowEvent } from "./types";

function sessionId(): string {
  const key = "autoopsReactSessionId";
  const current = window.localStorage.getItem(key);
  if (current) return current;
  const created = `react-${Date.now()}-${crypto.randomUUID()}`;
  window.localStorage.setItem(key, created);
  return created;
}

function completedResponse(event: WorkflowEvent): ChatResponse | null {
  if (event.event !== "completed") return null;
  const response = event.data.response;
  return response && typeof response === "object" ? (response as ChatResponse) : null;
}

export default function App() {
  const [events, setEvents] = useState<WorkflowEvent[]>([]);
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const controller = useRef<AbortController | null>(null);

  async function submit(value: ChatFormValue) {
    controller.current?.abort();
    const nextController = new AbortController();
    controller.current = nextController;
    setEvents([]);
    setResponse(null);
    setError("");
    setNotice("");
    setLoading(true);

    const request: ChatRequest = {
      ...value,
      top_k: 5,
      strategy: "hybrid",
      session_id: sessionId(),
    };
    try {
      await streamChat(
        request,
        (event) => {
          setEvents((current) => [...current, event]);
          const result = completedResponse(event);
          if (result) setResponse(result);
          if (event.event === "error") setError(event.message);
        },
        nextController.signal,
      );
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") {
        setNotice("已停止接收事件；服务端同步 I/O 可能仍在短暂完成。 ");
      } else {
        setError(caught instanceof Error ? caught.message : "请求失败");
      }
    } finally {
      if (controller.current === nextController) {
        controller.current = null;
        setLoading(false);
      }
    }
  }

  function cancel() {
    controller.current?.abort();
  }

  return (
    <main className="app-shell">
      <header className="hero">
        <div>
          <span className="product-mark">AUTOOPS / RAG</span>
          <h1>工业手册故障辅助台</h1>
          <p>固定 LangGraph 工作流、受控工具与可追溯证据的现场演示。</p>
        </div>
        <div className="hero-status">
          <span><i className="status-light" /> Workflow event streaming</span>
          <span>非 token streaming</span>
          <a href="/" target="_blank" rel="noreferrer">旧版页面 ↗</a>
        </div>
      </header>

      <ChatForm loading={loading} onSubmit={submit} onCancel={cancel} />
      {(error || notice) && (
        <div className={error ? "alert error" : "alert notice"}>{error || notice}</div>
      )}

      <div className="main-grid">
        <WorkflowTimeline events={events} response={response} />
        <div className="result-stack">
          <AnswerPanel response={response} />
          <CitationPanel response={response} />
          <EvidencePanel evidence={response?.evidence ?? []} />
          <TracePanel response={response} />
        </div>
      </div>
      <footer>
        <span>只读知识辅助，不连接 PLC，不替代现场规程与有资质人员判断。</span>
        <span>{response ? `request_id: ${response.request_id}` : "等待请求"}</span>
      </footer>
    </main>
  );
}
