export type RegionKind = "table" | "line" | "text" | "keyvalue" | "ignore";

export interface Region {
  id: string;
  name: string;
  kind: RegionKind;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  page_number: number;
  engines: string[];
  manual_rows: number[];
  manual_cols: number[];
  options: Record<string, unknown>;
}

export interface Layout {
  document_id: string;
  page_number: number;
  page_width_pt: number;
  page_height_pt: number;
  regions: Region[];
}

export interface PageGrid {
  page_number: number;
  width: number;
  height: number;
  row_lines: number[];
  col_lines: number[];
}

export interface Cell {
  row: number;
  col: number;
  bbox: number[];
  text: string;
  confidence: number | null;
  ink: number | null;
  status: "ok" | "low" | "blank";
}

export interface RegionResult {
  kind: "table" | "text" | "keyvalue";
  rows?: number;
  cols?: number;
  cells?: Cell[][];
  text?: string;
  key?: string;
  value?: string;
  method?: string;
}

export interface RegionRunResultRow {
  run_id: string;
  region_id: string;
  engine_id: string;
  status: string;
  duration_ms: number;
  error: string | null;
  result: RegionResult | null;
}

export interface RunSummary {
  id: string;
  document_id: string;
  page_number: number;
  status: string;
  error: string | null;
  created_at: number;
  finished_at: number | null;
}

export interface RegionRunDetail {
  id: string;
  document_id: string;
  page_number: number;
  status: string;
  error: string | null;
  results: RegionRunResultRow[];
}

export interface RegionProgressEvent {
  type: "start" | "region" | "engine" | "done";
  run_id?: string;
  total?: number;
  completed?: number;
  region_id?: string;
  engine_id?: string;
  engines?: string[];
  ok?: boolean;
  status?: string;
  failures?: number;
}

export interface TemplateSummary {
  id: string;
  name: string;
  page_width_pt: number;
  page_height_pt: number;
  region_count: number;
  created_at: number;
}

export interface DocumentSummary {
  id: string;
  filename: string;
  page_count: number;
  classification: string;
  created_at: number;
}

export const REGION_KIND_LABELS: Record<RegionKind, string> = {
  table: "Table",
  line: "Single line",
  text: "Text block",
  keyvalue: "Key-value",
  ignore: "Ignore",
};

export const REGION_KIND_COLORS: Record<RegionKind, string> = {
  table: "#4da3ff",
  line: "#3fb950",
  text: "#d29922",
  keyvalue: "#bc8cff",
  ignore: "#f85149",
};
