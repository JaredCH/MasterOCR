export interface EngineInfo {
  id: string;
  name: string;
  vendor: string;
  tier: number;
  kind: string;
  license: string;
  license_note: string;
  output: string;
  cost_per_page_usd: number;
  free_tier: string | null;
  requires_key: string | null;
  requires_gpu: boolean;
  requires_heavy: boolean;
  notes: string;
  tags: string[];
  available: boolean;
  unavailable_reason: string | null;
}

export interface EngineListResponse {
  engines: EngineInfo[];
  tier_counts: Record<string, number>;
  available_count: number;
}

export interface UploadResponse {
  document_id: string;
  filename: string;
  page_count: number;
  classification: string;
  pages: Array<{
    number: number;
    classification: string;
    text_chars: number;
    image_count: number;
  }>;
}

export interface RunPage {
  page_number: number;
  text: string | null;
  markdown: string | null;
  html: string | null;
  confidence: number | null;
}

export interface RunMetrics {
  cer: number | null;
  wer: number | null;
  reference: string | null;
  hallucination?: {
    repetition_ratio: number;
    novel_token_rate: number;
    prose_ratio: number;
    length_zscore: number;
    garbage_ratio: number;
    flags: string[];
  };
  dimensions?: {
    missed: number;
    invented: number;
    detail: Record<string, { reference: number; candidate: number }>;
  };
  tables?: { applicable: boolean; row_delta: number; cell_delta: number };
}

export interface Run {
  id: string;
  engine_id: string;
  status: string;
  duration_ms: number;
  error: string | null;
  pages: RunPage[];
  metrics: RunMetrics | null;
}

export interface DocumentDetail {
  id: string;
  filename: string;
  page_count: number;
  classification: string;
  pages: Array<{
    page_number: number;
    classification: string;
    text_chars: number;
    image_count: number;
    image_path: string | null;
  }>;
  runs: Run[];
  scores: Record<string, { engine_id: string; stars: number; notes: string | null }>;
}

export interface ProgressEvent {
  type: "start" | "engine" | "done";
  total?: number;
  completed?: number;
  engine_id?: string;
  ok?: boolean;
  duration_ms?: number;
  error?: string | null;
  engines?: string[];
}
