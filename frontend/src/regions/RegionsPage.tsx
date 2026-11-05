import { useCallback, useEffect, useRef, useState } from "react";
import {
  applyTemplate,
  createTemplate,
  deleteTemplate,
  fetchLayout,
  fetchLatestRegionResults,
  fetchPageGrid,
  listDocuments,
  listTemplates,
  pageImageUrl,
  saveLayout,
  startRegionRun,
  subscribeRegionProgress,
  uploadPdf,
} from "./api";
import type { EngineInfo } from "../types";
import type {
  DocumentSummary,
  Layout,
  PageGrid,
  Region,
  RegionKind,
  RegionProgressEvent,
  RegionRunDetail,
  TemplateSummary,
} from "./types";
import RegionCanvas from "./RegionCanvas";
import RegionList from "./RegionList";
import RegionResults from "./RegionResults";

type Phase = "pick" | "edit";

export default function RegionsPage() {
  const [phase, setPhase] = useState<Phase>("pick");
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [pageCount, setPageCount] = useState(1);
  const [pageNumber, setPageNumber] = useState(1);
  const [layout, setLayout] = useState<Layout | null>(null);
  const [grid, setGrid] = useState<PageGrid | null>(null);
  const [engines, setEngines] = useState<EngineInfo[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeKind, setActiveKind] = useState<RegionKind>("table");
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [results, setResults] = useState<RegionRunDetail["results"]>([]);
  const [progress, setProgress] = useState<RegionProgressEvent | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const unsubscribe = useRef<(() => void) | null>(null);

  useEffect(() => () => unsubscribe.current?.(), []);

  const refreshTemplates = useCallback(() => {
    listTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, []);

  useEffect(() => {
    listDocuments().then(setDocuments).catch(() => setDocuments([]));
    fetch("/api/engines")
      .then((response) => response.json())
      .then((data) => setEngines(data.engines ?? []))
      .catch(() => setEngines([]));
    refreshTemplates();
  }, [refreshTemplates]);

  const openDocument = useCallback(
    async (id: string, pages: number) => {
      setDocumentId(id);
      setPageCount(pages);
      setPageNumber(1);
      setPhase("edit");
      setResults([]);
      setError(null);
      try {
        const [fetchedLayout, fetchedGrid, latestResults] = await Promise.all([
          fetchLayout(id, 1),
          fetchPageGrid(id, 1),
          fetchLatestRegionResults(id, 1).catch(() => ({ results: [] })),
        ]);
        setLayout(fetchedLayout);
        setGrid(fetchedGrid);
        setResults(latestResults.results ?? []);
      } catch (err) {
        setError((err as Error).message);
      }
    },
    []
  );

  const handleUpload = useCallback(
    async (file: File) => {
      setError(null);
      try {
        const uploaded = await uploadPdf(file);
        const detail = await fetch(
          `/api/documents/${uploaded.document_id}`
        ).then((response) => response.json());
        await openDocument(uploaded.document_id, detail.page_count ?? 1);
      } catch (err) {
        setError((err as Error).message);
      }
    },
    [openDocument]
  );

  const switchPage = useCallback(
    async (page: number) => {
      if (!documentId) return;
      setPageNumber(page);
      setSelectedId(null);
      setResults([]);
      try {
        const [fetchedLayout, fetchedGrid, latestResults] = await Promise.all([
          fetchLayout(documentId, page),
          fetchPageGrid(documentId, page),
          fetchLatestRegionResults(documentId, page).catch(() => ({
            results: [],
          })),
        ]);
        setLayout(fetchedLayout);
        setGrid(fetchedGrid);
        setResults(latestResults.results ?? []);
      } catch (err) {
        setError((err as Error).message);
      }
    },
    [documentId]
  );

  const persist = useCallback(
    async (regions: Region[]) => {
      if (!documentId || !layout) return;
      setLayout({ ...layout, regions });
      setDirty(true);
    },
    [documentId, layout]
  );

  const saveNow = useCallback(async () => {
    if (!documentId || !layout) return;
    try {
      await saveLayout(documentId, pageNumber, {
        page_width_pt: layout.page_width_pt || 612,
        page_height_pt: layout.page_height_pt || 792,
        regions: layout.regions,
      });
      setDirty(false);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [documentId, layout, pageNumber]);

  const runRegions = useCallback(async () => {
    if (!documentId) return;
    setError(null);
    try {
      await saveNow();
      const started = await startRegionRun(documentId, pageNumber, [], []);
      setRunning(true);
      unsubscribe.current = subscribeRegionProgress(
        documentId,
        started.run_id,
        (event) => setProgress(event),
        async () => {
          setRunning(false);
          const detail = await fetchRegionRunSafe(documentId, started.run_id);
          if (detail) setResults(detail.results);
        }
      );
    } catch (err) {
      setError((err as Error).message);
      setRunning(false);
    }
  }, [documentId, pageNumber, saveNow]);

  const fetchRegionRunSafe = async (
    documentId: string,
    runId: string
  ): Promise<RegionRunDetail | null> => {
    try {
      return await fetchRegionRunDirect(documentId, runId);
    } catch {
      return null;
    }
  };

  const updateRegion = useCallback(
    (id: string, patch: Partial<Region>) => {
      if (!layout) return;
      persist(
        layout.regions.map((region) =>
          region.id === id ? { ...region, ...patch } : region
        )
      );
    },
    [layout, persist]
  );

  const deleteRegion = useCallback(
    (id: string) => {
      if (!layout) return;
      persist(layout.regions.filter((region) => region.id !== id));
      if (selectedId === id) setSelectedId(null);
    },
    [layout, persist, selectedId]
  );

  const duplicateRegion = useCallback(
    (id: string) => {
      if (!layout) return;
      const source = layout.regions.find((region) => region.id === id);
      if (!source) return;
      const copy: Region = {
        ...source,
        id: `r_${Math.random().toString(36).slice(2, 9)}`,
        name: `${source.name} copy`,
        x0: clamp(source.x0 + 0.02),
        x1: clamp(source.x1 + 0.02),
        y0: clamp(source.y0 + 0.02),
        y1: clamp(source.y1 + 0.02),
      };
      persist([...layout.regions, copy]);
    },
    [layout, persist]
  );

  const saveAsTemplate = useCallback(async () => {
    if (!documentId) return;
    const name = window.prompt("Template name:");
    if (!name) return;
    try {
      await saveNow();
      await createTemplate(name, documentId, pageNumber);
      refreshTemplates();
    } catch (err) {
      setError((err as Error).message);
    }
  }, [documentId, pageNumber, saveNow, refreshTemplates]);

  const applyTemplateById = useCallback(
    async (templateId: string) => {
      if (!documentId) return;
      try {
        await applyTemplate(documentId, pageNumber, templateId);
        const fetched = await fetchLayout(documentId, pageNumber);
        setLayout(fetched);
        setDirty(false);
      } catch (err) {
        setError((err as Error).message);
      }
    },
    [documentId, pageNumber]
  );

  if (phase === "pick") {
    return (
      <div className="app">
        <header className="masthead">
          <div>
            <h1>Region capture</h1>
            <p className="tagline">
              Draw named regions on a page — tables, single lines, ignore areas —
              then run OCR per region and get true tables with blank cells
              preserved.
            </p>
          </div>
        </header>
        {error && <div className="banner error">{error}</div>}
        <section className="panel">
          <h2>Open a document</h2>
          <label className="dropzone">
            <input
              type="file"
              accept="application/pdf"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void handleUpload(file);
              }}
            />
            <span>Upload a new PDF</span>
            <small>Max 50 MB · first 25 pages are rendered</small>
          </label>
          {documents.length > 0 && (
            <>
              <h2>…or pick a recent one</h2>
              <ul className="doc-picker">
                {documents.map((doc) => (
                  <li key={doc.id}>
                    <button
                      type="button"
                      onClick={() => void openDocument(doc.id, doc.page_count)}
                    >
                      <strong>{doc.filename}</strong>
                      <span className="hint">
                        {doc.page_count} pages · {new Date(doc.created_at * 1000).toLocaleString()}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      </div>
    );
  }

  const regions = layout?.regions ?? [];
  const completed = progress?.completed ?? 0;
  const total = progress?.total ?? 0;
  const currentEngine =
    progress?.type === "engine" ? progress.engine_id : null;
  const currentRegionName =
    progress?.type === "engine" && progress.region_id
      ? regions.find((r) => r.id === progress.region_id)?.name
      : null;

  return (
    <div className="app wide">
      <header className="masthead">
        <div>
          <h1>Region capture</h1>
          <p className="tagline">
            Draw regions, name them, run OCR per region, and get true tables.
          </p>
        </div>
        <div className="actions">
          <button type="button" onClick={() => setPhase("pick")}>
            ← Documents
          </button>
        </div>
      </header>

      {error && <div className="banner error">{error}</div>}

      <section className="panel">
        <div className="doc-header">
          <div className="pager">
            {Array.from({ length: pageCount }, (_, index) => index + 1).map(
              (page) => (
                <button
                  key={page}
                  type="button"
                  className={pageNumber === page ? "on" : ""}
                  onClick={() => void switchPage(page)}
                >
                  {page}
                </button>
              )
            )}
          </div>
          <div className="actions">
            <label className="kind-picker">
              Draw as:
              <select
                value={activeKind}
                onChange={(event) =>
                  setActiveKind(event.target.value as RegionKind)
                }
              >
                <option value="table">Table</option>
                <option value="line">Single line</option>
                <option value="text">Text block</option>
                <option value="keyvalue">Key-value</option>
                <option value="ignore">Ignore</option>
              </select>
            </label>
            <button type="button" onClick={() => void saveNow()} disabled={!dirty}>
              {dirty ? "Save layout*" : "Layout saved"}
            </button>
            <button
              type="button"
              className="accent"
              onClick={() => void runRegions()}
              disabled={running || regions.every((region) => region.kind === "ignore")}
            >
              {running
                ? currentEngine
                  ? `Running ${completed}/${total} · ${currentRegionName ?? ""} · ${currentEngine}…`
                  : `Running ${completed}/${total}…`
                : "Run regions"}
            </button>
          </div>
        </div>
        {running && (
          <div className="progress-track">
            <div
              className="progress-fill"
              style={{
                width: `${total ? (completed / total) * 100 : 5}%`,
              }}
            />
          </div>
        )}
      </section>

      <div className="region-workspace">
        <RegionCanvas
          imageUrl={pageImageUrl(documentId!, pageNumber)}
          regions={regions}
          grid={grid}
          selectedId={selectedId}
          activeKind={activeKind}
          onSelect={setSelectedId}
          onChange={persist}
        />
        <div className="region-side">
          <RegionList
            regions={regions}
            engines={engines}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onUpdate={updateRegion}
            onDelete={deleteRegion}
            onDuplicate={duplicateRegion}
          />
          <section className="panel">
            <h2>Templates</h2>
            <p className="hint">
              Save this page's layout as a named template, or apply one to this
              page.
            </p>
            <div className="actions">
              <button type="button" onClick={() => void saveAsTemplate()}>
                Save layout as template
              </button>
            </div>
            {templates.length > 0 && (
              <ul className="template-list">
                {templates.map((template) => (
                  <li key={template.id}>
                    <span>
                      <strong>{template.name}</strong>
                      <span className="hint">
                        {" "}
                        · {template.region_count} regions
                      </span>
                    </span>
                    <span className="actions">
                      <button
                        type="button"
                        onClick={() => void applyTemplateById(template.id)}
                      >
                        Apply
                      </button>
                      <button
                        type="button"
                        className="danger"
                        onClick={() => {
                          void deleteTemplate(template.id).then(refreshTemplates);
                        }}
                      >
                        ×
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>

      <RegionResults
        regions={regions}
        results={results}
        documentId={documentId!}
        pageNumber={pageNumber}
      />
    </div>
  );
}

function clamp(value: number): number {
  return Math.max(0, Math.min(1, value));
}

async function fetchRegionRunDirect(
  documentId: string,
  runId: string
): Promise<RegionRunDetail> {
  const response = await fetch(
    `/api/documents/${documentId}/regions/runs/${runId}`
  );
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
