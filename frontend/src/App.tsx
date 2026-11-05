import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchDocument,
  fetchEngines,
  saveScore,
  startRun,
  subscribeProgress,
  uploadPdf,
} from "./api";
import type {
  DocumentDetail,
  EngineInfo,
  ProgressEvent,
  Run,
} from "./types";

type Phase = "idle" | "uploading" | "running" | "done";

const TIER_LABELS: Record<number, string> = {
  1: "Core CPU",
  2: "Heavy CPU",
  3: "Free API",
  4: "Paid API",
  5: "GPU only",
};

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function ms(value: number): string {
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

export default function App() {
  const [engines, setEngines] = useState<EngineInfo[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [phase, setPhase] = useState<Phase>("idle");
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeEngine, setActiveEngine] = useState<string | null>(null);
  const [activePage, setActivePage] = useState(1);
  const [showUnavailable, setShowUnavailable] = useState(false);
  const unsubscribe = useRef<(() => void) | null>(null);

  useEffect(() => {
    fetchEngines()
      .then((data) => {
        setEngines(data.engines);
        setSelected(
          new Set(data.engines.filter((engine) => engine.available).map((e) => e.id))
        );
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => () => unsubscribe.current?.(), []);

  const available = useMemo(
    () => engines.filter((engine) => engine.available),
    [engines]
  );
  const unavailable = useMemo(
    () => engines.filter((engine) => !engine.available),
    [engines]
  );

  const handleUpload = useCallback(
    async (file: File) => {
      setError(null);
      setPhase("uploading");
      setDocument(null);
      setProgress(null);
      try {
        const uploaded = await uploadPdf(file);
        setDocumentId(uploaded.document_id);
        setPhase("running");
        await startRun(uploaded.document_id, [...selected]);
        unsubscribe.current = subscribeProgress(
          uploaded.document_id,
          (event) => setProgress(event),
          async () => {
            const detail = await fetchDocument(uploaded.document_id);
            setDocument(detail);
            setActiveEngine(detail.runs.find((run) => run.status === "ok")?.engine_id ?? null);
            setPhase("done");
          }
        );
      } catch (err) {
        setError((err as Error).message);
        setPhase("idle");
      }
    },
    [selected]
  );

  const toggleEngine = (id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleScore = async (engineId: string, stars: number) => {
    if (!documentId) return;
    await saveScore(documentId, engineId, stars, "");
    const detail = await fetchDocument(documentId);
    setDocument(detail);
  };

  const runs = document?.runs ?? [];
  // Engines that produced no text have no CER. Rank them after every engine
  // that did produce text, rather than letting a null sort to the top.
  const ranked = useMemo(
    () =>
      [...runs]
        .filter((run) => run.status === "ok")
        .sort((a, b) => {
          const aCer = a.metrics?.cer ?? null;
          const bCer = b.metrics?.cer ?? null;
          if (aCer === null && bCer === null) return 0;
          if (aCer === null) return 1;
          if (bCer === null) return -1;
          return aCer - bCer;
        }),
    [runs]
  );
  const activeRun = runs.find((run) => run.engine_id === activeEngine) ?? null;

  return (
    <div className="app">
      <header className="masthead">
        <div>
          <h1>MasterOCR</h1>
          <p className="tagline">
            Run PDF isometrics and schematics through every configured OCR engine
            and compare the results side by side.
          </p>
        </div>
        <div className="counts">
          <span className="pill">{engines.length} engines</span>
          <span className="pill accent">{available.length} runnable</span>
        </div>
      </header>

      {error && <div className="banner error">{error}</div>}

      {phase === "idle" && (
        <section className="panel">
          <h2>1. Choose engines</h2>
          <p className="hint">
            {selected.size} of {available.length} runnable engines selected.
          </p>
          <div className="engine-grid">
            {available.map((engine) => (
              <label
                key={engine.id}
                className={`engine-card ${selected.has(engine.id) ? "on" : ""}`}
              >
                <input
                  type="checkbox"
                  checked={selected.has(engine.id)}
                  onChange={() => toggleEngine(engine.id)}
                />
                <div>
                  <strong>{engine.name}</strong>
                  <span className="meta">
                    {engine.vendor} · {TIER_LABELS[engine.tier]} · {engine.license}
                  </span>
                  <span className="notes">{engine.notes}</span>
                </div>
              </label>
            ))}
          </div>

          {unavailable.length > 0 && (
            <details
              className="unavailable"
              open={showUnavailable}
              onToggle={(event) =>
                setShowUnavailable((event.target as HTMLDetailsElement).open)
              }
            >
              <summary>{unavailable.length} engines not runnable here</summary>
              <ul>
                {unavailable.map((engine) => (
                  <li key={engine.id}>
                    <strong>{engine.name}</strong> — {engine.unavailable_reason}
                  </li>
                ))}
              </ul>
            </details>
          )}

          <h2>2. Upload a PDF</h2>
          <label className="dropzone">
            <input
              type="file"
              accept="application/pdf"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void handleUpload(file);
              }}
            />
            <span>Drop a PDF here or click to browse</span>
            <small>Max 50 MB · first 25 pages are processed</small>
          </label>
        </section>
      )}

      {(phase === "uploading" || phase === "running") && (
        <section className="panel">
          <h2>{phase === "uploading" ? "Uploading…" : "Running engines…"}</h2>
          {progress?.type === "engine" && (
            <p className="hint">
              {progress.completed} / {progress.total} complete — last:{" "}
              {progress.engine_id} ({progress.ok ? "ok" : "failed"})
            </p>
          )}
          <div className="progress-track">
            <div
              className="progress-fill"
              style={{
                width: `${
                  progress?.total
                    ? ((progress.completed ?? 0) / progress.total) * 100
                    : 5
                }%`,
              }}
            />
          </div>
        </section>
      )}

      {phase === "done" && document && (
        <>
          <section className="panel">
            <div className="doc-header">
              <div>
                <h2>{document.filename}</h2>
                <p className="hint">
                  {document.page_count} pages · classified as{" "}
                  <strong>{document.classification.replace("_", " ")}</strong>
                </p>
              </div>
              <div className="actions">
                <a href={`/api/documents/${document.id}/export.csv`}>Export CSV</a>
                <a href={`/api/documents/${document.id}/export.json`}>Export JSON</a>
                <button
                  onClick={() => {
                    setPhase("idle");
                    setDocument(null);
                    setDocumentId(null);
                    setProgress(null);
                  }}
                >
                  New document
                </button>
              </div>
            </div>
          </section>

          <section className="panel">
            <h2>Leaderboard</h2>
            <p className="hint">
              Sorted by character error rate against{" "}
              <strong>{ranked[0]?.metrics?.reference ?? "consensus"}</strong>. Lower
              is better.
            </p>
            <table className="leaderboard">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Engine</th>
                  <th>CER</th>
                  <th>WER</th>
                  <th>Time</th>
                  <th>Missed callouts</th>
                  <th>Flags</th>
                  <th>Your score</th>
                </tr>
              </thead>
              <tbody>
                {ranked.map((run, index) => (
                  <tr
                    key={run.id}
                    className={activeEngine === run.engine_id ? "active" : ""}
                    onClick={() => setActiveEngine(run.engine_id)}
                  >
                    <td>{index + 1}</td>
                    <td>
                      <strong>{run.engine_id}</strong>
                    </td>
                    <td>{pct(run.metrics?.cer)}</td>
                    <td>{pct(run.metrics?.wer)}</td>
                    <td>{ms(run.duration_ms)}</td>
                    <td>{run.metrics?.dimensions?.missed ?? "—"}</td>
                    <td>
                      {(run.metrics?.hallucination?.flags ?? []).map((flag) => (
                        <span key={flag} className="flag">
                          {flag}
                        </span>
                      ))}
                    </td>
                    <td onClick={(event) => event.stopPropagation()}>
                      <StarRating
                        value={document.scores[run.engine_id]?.stars ?? 0}
                        onChange={(stars) => void handleScore(run.engine_id, stars)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {runs.some((run) => run.status !== "ok") && (
              <details className="failures">
                <summary>
                  {runs.filter((run) => run.status !== "ok").length} engines failed
                </summary>
                <ul>
                  {runs
                    .filter((run) => run.status !== "ok")
                    .map((run) => (
                      <li key={run.id}>
                        <strong>{run.engine_id}</strong> — {run.error}
                      </li>
                    ))}
                </ul>
              </details>
            )}
          </section>

          {activeRun && (
            <section className="panel">
              <div className="doc-header">
                <h2>{activeRun.engine_id}</h2>
                <div className="pager">
                  {Array.from({ length: document.page_count }, (_, i) => i + 1).map(
                    (page) => (
                      <button
                        key={page}
                        className={activePage === page ? "on" : ""}
                        onClick={() => setActivePage(page)}
                      >
                        {page}
                      </button>
                    )
                  )}
                </div>
              </div>
              <div className="compare">
                <figure>
                  <img
                    src={`/api/documents/${document.id}/pages/${activePage}.png`}
                    alt={`Page ${activePage}`}
                  />
                  <figcaption>Source page {activePage}</figcaption>
                </figure>
                <div className="output">
                  <h3>Extracted text</h3>
                  <pre>{pageText(activeRun, activePage)}</pre>
                </div>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function pageText(run: Run, page: number): string {
  const match = run.pages.find((item) => item.page_number === page);
  if (!match) return "(no output for this page)";
  return match.markdown || match.text || match.html || "(empty)";
}

function StarRating({
  value,
  onChange,
}: {
  value: number;
  onChange: (stars: number) => void;
}) {
  return (
    <div className="stars">
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          className={star <= value ? "on" : ""}
          onClick={() => onChange(star)}
          aria-label={`${star} stars`}
        >
          ★
        </button>
      ))}
    </div>
  );
}
