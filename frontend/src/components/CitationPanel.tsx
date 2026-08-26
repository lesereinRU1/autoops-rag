import type { ChatResponse, SearchHit } from "../types";

function sourceLabel(hit: SearchHit): string {
  const metadataSource = hit.chunk.metadata.source;
  return hit.chunk.source_url || (typeof metadataSource === "string" ? metadataSource : "本地文档库");
}

function citedEvidence(response: ChatResponse): Array<{ hit: SearchHit; sourceNumber: number }> {
  const sourceNumbers = new Set<number>();
  for (const match of response.answer.matchAll(/\[来源\s*(\d+)/g)) {
    const sourceNumber = Number(match[1]);
    if (Number.isInteger(sourceNumber) && sourceNumber >= 1 && sourceNumber <= response.evidence.length) {
      sourceNumbers.add(sourceNumber);
    }
  }
  return [...sourceNumbers]
    .sort((left, right) => left - right)
    .map((sourceNumber) => ({ hit: response.evidence[sourceNumber - 1], sourceNumber }));
}

export function CitationPanel({ response }: { response: ChatResponse | null }) {
  const evidence = response?.evidence ?? [];
  const citations = response ? citedEvidence(response) : [];
  return (
    <section className="panel">
      <div className="section-heading compact">
        <div>
          <span className="eyebrow">CITATIONS</span>
          <h2>引用来源</h2>
        </div>
        <span className="event-count">{citations.length} cited / {evidence.length} evidence</span>
      </div>
      {citations.length === 0 ? (
        <p className="empty-state">
          {evidence.length === 0
            ? "本次回答没有可展示的引用证据。"
            : "回答中没有可解析的 [来源N]；下方 Evidence 仍保留本次最终证据池。"}
        </p>
      ) : (
        <div className="citation-list">
          {citations.map(({ hit, sourceNumber }) => (
            <details className="citation-card" key={hit.chunk.chunk_id}>
              <summary>
                <span className="source-number">{sourceNumber}</span>
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
