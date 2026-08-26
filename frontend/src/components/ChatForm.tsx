import { useState, type FormEvent } from "react";

export interface ChatFormValue {
  query: string;
  model: string;
  version: string;
}

interface ChatFormProps {
  loading: boolean;
  onSubmit: (value: ChatFormValue) => void;
  onCancel: () => void;
}

export function ChatForm({ loading, onSubmit, onCancel }: ChatFormProps) {
  const [query, setQuery] = useState(
    "请从 Siemens 官方资料“Modbus/TCP with MB_CLIENT and MB_SERVER”（Entry-ID 102020340）的 Table 1-1 和 Table 1-2 中，比较 S7-1200 作为 client/server 时的 connection setup、local port、remote port。",
  );
  const [model, setModel] = useState("S7-1200");
  const [version, setVersion] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim() || loading) {
      return;
    }
    onSubmit({ query: query.trim(), model, version: version.trim() });
  }

  return (
    <form className="query-card" onSubmit={submit}>
      <div className="section-heading">
        <div>
          <span className="eyebrow">ASK THE MANUAL</span>
          <h2>描述设备问题</h2>
        </div>
        <span className="scope-badge">只读 · 证据约束</span>
      </div>
      <label htmlFor="query">问题</label>
      <textarea
        id="query"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        rows={4}
        maxLength={500}
        disabled={loading}
      />
      <div className="form-grid">
        <label>
          设备型号
          <select
            value={model}
            onChange={(event) => setModel(event.target.value)}
            disabled={loading}
          >
            <option value="S7-1200">S7-1200</option>
            <option value="S7-1200 G2">S7-1200 G2</option>
            <option value="">不限定型号</option>
          </select>
        </label>
        <label>
          固件 / 手册版本
          <input
            value={version}
            onChange={(event) => setVersion(event.target.value)}
            placeholder="可选，例如 V4.6"
            disabled={loading}
          />
        </label>
      </div>
      <div className="form-actions">
        <button className="primary-button" type="submit" disabled={loading || !query.trim()}>
          {loading ? "工作流执行中…" : "开始分析"}
        </button>
        <button className="secondary-button" type="button" onClick={onCancel} disabled={!loading}>
          停止接收
        </button>
        <span className="helper-text">取消只停止前端接收；同步底层任务可能短暂继续。</span>
      </div>
    </form>
  );
}
