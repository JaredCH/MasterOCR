import { useMemo, useState } from "react";
import type { Region, RegionRunResultRow } from "./types";
import { REGION_KIND_COLORS } from "./types";

interface Props {
  regions: Region[];
  results: RegionRunResultRow[];
  documentId: string;
  pageNumber: number;
}

function downloadCsv(region: Region, row: RegionRunResultRow) {
  const cells = row.result?.cells;
  if (!cells) return;
  const lines = cells.map((rowCells) =>
    rowCells
      .map((cell) => `"${(cell.text ?? "").replace(/"/g, '""')}"`)
      .join(",")
  );
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${region.name.replace(/[^\w-]+/g, "_")}-${row.engine_id}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function RegionResults({
  regions,
  results,
  documentId,
  pageNumber,
}: Props) {
  const [engineTab, setEngineTab] = useState<Record<string, string>>({});

  const byRegion = useMemo(() => {
    const map = new Map<string, RegionRunResultRow[]>();
    for (const row of results) {
      const bucket = map.get(row.region_id) ?? [];
      bucket.push(row);
      map.set(row.region_id, bucket);
    }
    return map;
  }, [results]);

  const captured = regions.filter(
    (region) => region.kind !== "ignore" && byRegion.has(region.id)
  );

  if (captured.length === 0) {
    return (
      <section className="panel">
        <h2>Results</h2>
        <p className="hint">Run the regions to see extracted tables here.</p>
      </section>
    );
  }

  return (
    <>
      {captured.map((region) => {
        const rows = byRegion.get(region.id)!;
        const okRows = rows.filter((row) => row.status === "ok" && row.result);
        const chosenEngine =
          engineTab[region.id] && rows.some((row) => row.engine_id === engineTab[region.id])
            ? engineTab[region.id]
            : okRows[0]?.engine_id ?? rows[0]?.engine_id;
        const active = rows.find((row) => row.engine_id === chosenEngine);
        const color = REGION_KIND_COLORS[region.kind];

        return (
          <section className="panel" key={region.id}>
            <div className="doc-header">
              <div>
                <h2>
                  <span
                    className="kind-dot"
                    style={{ background: color }}
                  />
                  {region.name}
                  <span className="kind-badge">{region.kind}</span>
                </h2>
                {active && (
                  <p className="hint">
                    {active.engine_id} · {active.duration_ms} ms
                    {active.result?.method ? ` · ${active.result.method}` : ""}
                  </p>
                )}
              </div>
              <div className="actions">
                {active?.result?.kind === "table" && (
                  <button
                    type="button"
                    onClick={() => active && downloadCsv(region, active)}
                  >
                    Download CSV
                  </button>
                )}
              </div>
            </div>

            {rows.length > 1 && (
              <div className="engine-tabs">
                {rows.map((row) => (
                  <button
                    key={row.engine_id}
                    type="button"
                    className={row.engine_id === chosenEngine ? "on" : ""}
                    onClick={() =>
                      setEngineTab((current) => ({
                        ...current,
                        [region.id]: row.engine_id,
                      }))
                    }
                  >
                    {row.engine_id}
                    <span className={`status-dot ${row.status}`} />
                  </button>
                ))}
              </div>
            )}

            {active?.status !== "ok" && (
              <div className="banner error">
                {active?.error ?? "This engine produced no result."}
              </div>
            )}

            {active?.result?.kind === "table" && active.result.cells && (
              <div className="table-scroll">
                <table className="data-table">
                  <tbody>
                    {active.result.cells.map((rowCells, rowIndex) => (
                      <tr key={rowIndex}>
                        {rowCells.map((cell, colIndex) => (
                          <td
                            key={colIndex}
                            className={`cell-${cell.status}`}
                            title={
                              cell.confidence !== null
                                ? `confidence ${(cell.confidence * 100).toFixed(0)}%`
                                : undefined
                            }
                          >
                            {cell.text}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {active?.result &&
              (active.result.kind === "text" ||
                active.result.kind === "keyvalue") && (
                <div className="text-result">
                  {active.result.kind === "keyvalue" && active.result.key ? (
                    <div className="kv">
                      <span className="kv-key">{active.result.key}</span>
                      <span className="kv-value">{active.result.value}</span>
                    </div>
                  ) : (
                    <pre>{active.result.text}</pre>
                  )}
                </div>
              )}
          </section>
        );
      })}
      <section className="panel">
        <div className="doc-header">
          <h2>Exports</h2>
          <div className="actions">
            <a
              href={`/api/documents/${documentId}/regions/export.csv?page_number=${pageNumber}`}
            >
              Export all (CSV)
            </a>
            <a
              href={`/api/documents/${documentId}/regions/export.json?page_number=${pageNumber}`}
            >
              Export all (JSON)
            </a>
          </div>
        </div>
      </section>
    </>
  );
}
