import type {
  DocumentDetail,
  EngineListResponse,
  ProgressEvent,
  UploadResponse,
} from "./types";

const BASE = "/api";

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchEngines(): Promise<EngineListResponse> {
  return json<EngineListResponse>(await fetch(`${BASE}/engines`));
}

export async function uploadPdf(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${BASE}/documents`, { method: "POST", body: form });
  return json<UploadResponse>(response);
}

export async function startRun(
  documentId: string,
  engineIds: string[]
): Promise<{ document_id: string; engine_count: number }> {
  const response = await fetch(`${BASE}/documents/${documentId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ engine_ids: engineIds }),
  });
  return json<{ document_id: string; engine_count: number }>(response);
}

export async function fetchDocument(documentId: string): Promise<DocumentDetail> {
  return json<DocumentDetail>(await fetch(`${BASE}/documents/${documentId}`));
}

export async function saveScore(
  documentId: string,
  engineId: string,
  stars: number,
  notes: string
): Promise<{ ok: boolean }> {
  const response = await fetch(`${BASE}/documents/${documentId}/scores`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ engine_id: engineId, stars, notes }),
  });
  return json<{ ok: boolean }>(response);
}

export function subscribeProgress(
  documentId: string,
  onEvent: (event: ProgressEvent) => void,
  onDone: () => void
): () => void {
  const source = new EventSource(`${BASE}/documents/${documentId}/progress`);
  source.onmessage = (message) => {
    const event = JSON.parse(message.data) as ProgressEvent;
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
