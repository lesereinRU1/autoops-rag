import type { SearchHit } from "../types";

function sourceLabel(hit: SearchHit): string {
  const metadataSource = hit.chunk.metadata.source;
  return hit.chunk.source_url || (typeof metadataSource === "string" ? metadataSource : "本地文档库");
}

export function CitationPanel({ evidence }: { evidence: SearchHit[] }) {
  return (
    <section className="panel">
      <div className="section-heading compact">
        <div>
          <span className="eyebrow">CITATIONS</span>
          <h2>引用来源</h2>
        </div>
        <span className="event-count">{evidence.length} sources</span>
      </div>
      {evidence.length === 0 ? (
        <p className="empty-state">本次回答没有可展示的引用证据。</p>
      ) : (
        <div className="citation-list">
          {evidence.map((hit, index) => (
            <details className="citation-card" key={hit.chunk.chunk_id}>
              <summary>
                <span className="source-number">{index + 1}</span>
                <span>
                  <strong>{hit.chunk.doc_name}</strong>
                  <small>第 {hit.chunk.page} 页 · score {(hit.rerank_score ?? hit.score).toFixed(4)}</small>
                </span>
              </summary>
              <dl className="detail-grid">
                <dt>chunk</dt>
                <dd>{hit.chunk.chunk_id}</dd>
                <dt>source</dt>
                <dd>{sourceLabel(hit)}</dd>
                <dt>章节</dt>
                <dd>{hit.chunk.section_path.join(" › ") || "未标注"}</dd>
              </dl>
            </details>
          ))}
        </div>
      )}
    </section>
  );
}
