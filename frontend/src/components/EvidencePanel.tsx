import type { SearchHit } from "../types";

export function EvidencePanel({ evidence }: { evidence: SearchHit[] }) {
  return (
    <details className="panel collapsible" open={false}>
      <summary>
        <span>
          <span className="eyebrow">RETRIEVAL EVIDENCE</span>
          <strong>查看检索 Evidence</strong>
        </span>
        <span>{evidence.length} chunks</span>
      </summary>
      <div className="evidence-list">
        {evidence.length === 0 ? (
          <p className="empty-state">没有检索到证据。</p>
        ) : (
          evidence.map((hit) => (
            <article className="evidence-card" key={hit.chunk.chunk_id}>
              <div className="evidence-header">
                <div>
                  <strong>{hit.chunk.doc_name}</strong>
                  <small>第 {hit.chunk.page} 页 · {hit.chunk.chunk_id}</small>
                </div>
                <span className="score-chip">{(hit.rerank_score ?? hit.score).toFixed(4)}</span>
              </div>
              <p>{hit.chunk.text.slice(0, 900)}</p>
              <details className="metadata-details">
                <summary>provenance / metadata</summary>
                <pre>{JSON.stringify({ source_url: hit.chunk.source_url, ...hit.chunk.metadata }, null, 2)}</pre>
              </details>
            </article>
          ))
        )}
      </div>
    </details>
  );
}
