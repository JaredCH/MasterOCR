import type {
  DocumentSummary,
  Layout,
  PageGrid,
  Region,
  RegionProgressEvent,
  RegionRunDetail,
  RunSummary,
  TemplateSummary,
} from "./types";

const BASE = "/api";

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  return json<DocumentSummary[]>(await fetch(`${BASE}/documents`));
}

export async function uploadPdf(file: File): Promise<{ document_id: string }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${BASE}/documents`, {
    method: "POST",
    body: form,
  });
  return json<{ document_id: string }>(response);
}

export async function fetchLayout(
  documentId: string,
  pageNumber: number
): Promise<Layout> {
  return json<Layout>(
    await fetch(`${BASE}/documents/${documentId}/layouts/${pageNumber}`)
  );
}

export async function saveLayout(
  documentId: string,
  pageNumber: number,
  layout: {
    page_width_pt: number;
    page_height_pt: number;
    regions: Region[];
  }
): Promise<{ ok: boolean; region_count: number }> {
  const response = await fetch(
    `${BASE}/documents/${documentId}/layouts/${pageNumber}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page_number: pageNumber, ...layout }),
    }
  );
  return json(response);
}

export async function fetchPageGrid(
  documentId: string,
  pageNumber: number
): Promise<PageGrid> {
  return json<PageGrid>(
    await fetch(`${BASE}/documents/${documentId}/pages/${pageNumber}/grid`)
  );
}

export async function startRegionRun(
  documentId: string,
  pageNumber: number,
  regionIds: string[],
  engineIds: string[]
): Promise<{ run_id: string; region_count: number }> {
  const response = await fetch(`${BASE}/documents/${documentId}/regions/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      page_number: pageNumber,
      region_ids: regionIds,
      engine_ids: engineIds,
    }),
  });
  return json(response);
}

export function subscribeRegionProgress(
  documentId: string,
  runId: string,
  onEvent: (event: RegionProgressEvent) => void,
  onDone: () => void
): () => void {
  const source = new EventSource(
    `${BASE}/documents/${documentId}/regions/runs/${runId}/progress`
  );
  source.onmessage = (message) => {
    const event = JSON.parse(message.data) as RegionProgressEvent;
    onEvent(event);
    if (event.type === "done") {
      source.close();
      onDone();
    }
  };
  source.onerror = () => {
    source.close();
    onDone();
  };
  return () => source.close();
}

export async function fetchRegionRun(
  documentId: string,
  runId: string
): Promise<RegionRunDetail> {
  return json<RegionRunDetail>(
    await fetch(`${BASE}/documents/${documentId}/regions/runs/${runId}`)
  );
}

export async function listRegionRuns(
  documentId: string,
  pageNumber: number
): Promise<{ runs: RunSummary[] }> {
  return json(
    await fetch(
      `${BASE}/documents/${documentId}/regions/runs?page_number=${pageNumber}`
    )
  );
}

export async function fetchLatestRegionResults(
  documentId: string,
  pageNumber: number
): Promise<{ results: RegionRunDetail["results"] }> {
  return json(
    await fetch(
      `${BASE}/documents/${documentId}/regions/results?page_number=${pageNumber}`
    )
  );
}

export async function listTemplates(): Promise<TemplateSummary[]> {
  return json<TemplateSummary[]>(await fetch(`${BASE}/templates`));
}

export async function createTemplate(
  name: string,
  documentId: string,
  pageNumber: number
): Promise<{ ok: boolean; template_id: string }> {
  const response = await fetch(`${BASE}/templates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      document_id: documentId,
      page_number: pageNumber,
    }),
  });
  return json(response);
}

export async function deleteTemplate(templateId: string): Promise<void> {
  await fetch(`${BASE}/templates/${templateId}`, { method: "DELETE" });
}

export async function applyTemplate(
  documentId: string,
  pageNumber: number,
  templateId: string
): Promise<{ ok: boolean; region_count: number }> {
  const response = await fetch(
    `${BASE}/documents/${documentId}/layouts/${pageNumber}/apply-template/${templateId}`,
    { method: "POST" }
  );
  return json(response);
}

export function regionExportCsvUrl(documentId: string, pageNumber: number): string {
  return `${BASE}/documents/${documentId}/regions/export.csv?page_number=${pageNumber}`;
}

export function regionExportJsonUrl(documentId: string, pageNumber: number): string {
  return `${BASE}/documents/${documentId}/regions/export.json?page_number=${pageNumber}`;
}

export function pageImageUrl(documentId: string, pageNumber: number): string {
  return `${BASE}/documents/${documentId}/pages/${pageNumber}.png`;
}
