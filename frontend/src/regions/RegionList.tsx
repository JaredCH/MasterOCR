import type { EngineInfo } from "../types";
import type { Region, RegionKind } from "./types";
import { REGION_KIND_COLORS, REGION_KIND_LABELS } from "./types";

interface Props {
  regions: Region[];
  engines: EngineInfo[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onUpdate: (id: string, patch: Partial<Region>) => void;
  onDelete: (id: string) => void;
  onDuplicate: (id: string) => void;
}

const KINDS: RegionKind[] = ["table", "line", "text", "keyvalue", "ignore"];

// Engines that make sense per region kind. Text-layer engines are useless on
// a cropped image; table/docparse engines only make sense on table regions.
function engineFilter(kind: RegionKind, engine: EngineInfo): boolean {
  if (!engine.available) return false;
  if (kind === "table") {
    return ["ocr", "table", "docparse", "vlm-api"].includes(engine.kind);
  }
  if (kind === "ignore") return false;
  return ["ocr", "vlm-api"].includes(engine.kind);
}

export default function RegionList({
  regions,
  engines,
  selectedId,
  onSelect,
  onUpdate,
  onDelete,
  onDuplicate,
}: Props) {
  return (
    <div className="region-list">
      <h2>Regions</h2>
      <p className="hint">
        Pick a tool, then drag on the canvas to draw. Name each region before a
        run — names appear in the exports.
      </p>
      {regions.length === 0 && (
        <p className="hint">No regions yet. Draw one on the page.</p>
      )}
      {regions.map((region) => {
        const selected = region.id === selectedId;
        const usable = engines.filter((engine) =>
          engineFilter(region.kind, engine)
        );
        return (
          <div
            key={region.id}
            className={`region-card ${selected ? "selected" : ""}`}
            style={{ borderLeftColor: REGION_KIND_COLORS[region.kind] }}
            onClick={() => onSelect(region.id)}
          >
            <div className="region-card-row">
              <input
                className="region-name"
                value={region.name}
                onChange={(event) =>
                  onUpdate(region.id, { name: event.target.value })
                }
                onClick={(event) => event.stopPropagation()}
              />
              <select
                value={region.kind}
                onChange={(event) =>
                  onUpdate(region.id, {
                    kind: event.target.value as RegionKind,
                    engines: [],
                  })
                }
                onClick={(event) => event.stopPropagation()}
              >
                {KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {REGION_KIND_LABELS[kind]}
                  </option>
                ))}
              </select>
            </div>
            {region.kind !== "ignore" && (
              <details className="region-engines">
                <summary>
                  {region.engines.length === 0
                    ? "Default engines"
                    : `${region.engines.length} engine(s) selected`}
                </summary>
                <div className="engine-checks">
                  {usable.map((engine) => (
                    <label key={engine.id} className="engine-check">
                      <input
                        type="checkbox"
                        checked={region.engines.includes(engine.id)}
                        onChange={(event) => {
                          const next = event.target.checked
                            ? [...region.engines, engine.id]
                            : region.engines.filter((id) => id !== engine.id);
                          onUpdate(region.id, { engines: next });
                        }}
                      />
                      <span>{engine.name}</span>
                    </label>
                  ))}
                </div>
              </details>
            )}
            <div className="region-actions">
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  onDuplicate(region.id);
                }}
              >
                Duplicate
              </button>
              <button
                type="button"
                className="danger"
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete(region.id);
                }}
              >
                Delete
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
