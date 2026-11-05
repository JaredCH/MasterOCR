import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { PageGrid, Region, RegionKind } from "./types";
import { REGION_KIND_COLORS } from "./types";

export interface CanvasProps {
  imageUrl: string;
  regions: Region[];
  grid: PageGrid | null;
  selectedId: string | null;
  activeKind: RegionKind;
  onSelect: (id: string | null) => void;
  onChange: (regions: Region[]) => void;
}

type DragMode =
  | { type: "none" }
  | { type: "draw"; startX: number; startY: number }
  | { type: "move"; id: string; dx: number; dy: number }
  | { type: "resize"; id: string; handle: string };

const SNAP_PX = 8;

function uid(): string {
  return `r_${Math.random().toString(36).slice(2, 9)}`;
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function normRect(region: Region): { x: number; y: number; w: number; h: number } {
  return {
    x: Math.min(region.x0, region.x1),
    y: Math.min(region.y0, region.y1),
    w: Math.abs(region.x1 - region.x0),
    h: Math.abs(region.y1 - region.y0),
  };
}

/** Snap a normalized coordinate to the nearest detected line within range. */
function snap(value: number, lines: number[], tolerance: number): number {
  let best = value;
  let bestDist = tolerance;
  for (const line of lines) {
    const dist = Math.abs(line - value);
    if (dist < bestDist) {
      bestDist = dist;
      best = line;
    }
  }
  return best;
}

export default function RegionCanvas({
  imageUrl,
  regions,
  grid,
  selectedId,
  activeKind,
  onSelect,
  onChange,
}: CanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });
  const [zoom, setZoom] = useState(1);
  const [drag, setDrag] = useState<DragMode>({ type: "none" });
  const [draft, setDraft] = useState<Region | null>(null);
  const [spaceDown, setSpaceDown] = useState(false);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const panStart = useRef<{ x: number; y: number } | null>(null);

  const colLines = useMemo(() => grid?.col_lines ?? [], [grid]);
  const rowLines = useMemo(() => grid?.row_lines ?? [], [grid]);

  useEffect(() => {
    const image = new Image();
    image.onload = () =>
      setImageSize({ width: image.naturalWidth, height: image.naturalHeight });
    image.src = imageUrl;
  }, [imageUrl]);

  // Keyboard: delete selected, arrow-key nudge, space for pan.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.code === "Space") {
        setSpaceDown(true);
        return;
      }
      if (!selectedId) return;
      const target = event.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;

      if (event.key === "Delete" || event.key === "Backspace") {
        onChange(regions.filter((region) => region.id !== selectedId));
        onSelect(null);
        return;
      }
      const step = event.shiftKey ? 0.01 : 0.002;
      const deltas: Record<string, [number, number]> = {
        ArrowLeft: [-step, 0],
        ArrowRight: [step, 0],
        ArrowUp: [0, -step],
        ArrowDown: [0, step],
      };
      const delta = deltas[event.key];
      if (!delta) return;
      event.preventDefault();
      onChange(
        regions.map((region) =>
          region.id === selectedId
            ? {
                ...region,
                x0: clamp01(region.x0 + delta[0]),
                x1: clamp01(region.x1 + delta[0]),
                y0: clamp01(region.y0 + delta[1]),
                y1: clamp01(region.y1 + delta[1]),
              }
            : region
        )
      );
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.code === "Space") setSpaceDown(false);
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [regions, selectedId, onChange, onSelect]);

  const toNormalized = useCallback(
    (clientX: number, clientY: number) => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect || !imageSize.width) return { x: 0, y: 0 };
      const scale = imageSize.width * zoom / rect.width;
      const x = ((clientX - rect.left) * scale) / imageSize.width;
      const y = ((clientY - rect.top) * scale) / imageSize.height;
      return { x: clamp01(x), y: clamp01(y) };
    },
    [imageSize, zoom]
  );

  const onPointerDown = (event: React.PointerEvent) => {
    if (spaceDown) {
      panStart.current = { x: event.clientX - pan.x, y: event.clientY - pan.y };
      (event.target as HTMLElement).setPointerCapture(event.pointerId);
      return;
    }
    const point = toNormalized(event.clientX, event.clientY);
    const hit = regions.find((region) => {
      const rect = normRect(region);
      return (
        point.x >= rect.x &&
        point.x <= rect.x + rect.w &&
        point.y >= rect.y &&
        point.y <= rect.y + rect.h
      );
    });
    if (hit) {
      onSelect(hit.id);
      setDrag({ type: "move", id: hit.id, dx: point.x, dy: point.y });
    } else {
      onSelect(null);
      const snapped = {
        x: snap(point.x, colLines, SNAP_PX / (imageSize.width || 1)),
        y: snap(point.y, rowLines, SNAP_PX / (imageSize.height || 1)),
      };
      const newRegion: Region = {
        id: uid(),
        name: `${activeKind === "ignore" ? "Ignore" : "Region"} ${regions.length + 1}`,
        kind: activeKind,
        x0: snapped.x,
        y0: snapped.y,
        x1: snapped.x,
        y1: snapped.y,
        page_number: 1,
        engines: [],
        manual_rows: [],
        manual_cols: [],
        options: {},
      };
      setDraft(newRegion);
      setDrag({ type: "draw", startX: snapped.x, startY: snapped.y });
    }
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: React.PointerEvent) => {
    if (panStart.current) {
      setPan({
        x: event.clientX - panStart.current.x,
        y: event.clientY - panStart.current.y,
      });
      return;
    }
    if (drag.type === "none") return;
    const point = toNormalized(event.clientX, event.clientY);
    const snapX = snap(point.x, colLines, SNAP_PX / (imageSize.width || 1));
    const snapY = snap(point.y, rowLines, SNAP_PX / (imageSize.height || 1));

    if (drag.type === "draw" && draft) {
      setDraft({
        ...draft,
        x1: snapX,
        y1: snapY,
      });
    } else if (drag.type === "move") {
      const dx = point.x - drag.dx;
      const dy = point.y - drag.dy;
      onChange(
        regions.map((region) =>
          region.id === drag.id
            ? {
                ...region,
                x0: clamp01(region.x0 + dx),
                x1: clamp01(region.x1 + dx),
                y0: clamp01(region.y0 + dy),
                y1: clamp01(region.y1 + dy),
              }
            : region
        )
      );
      setDrag({ ...drag, dx: point.x, dy: point.y });
    } else if (drag.type === "resize") {
      onChange(
        regions.map((region) => {
          if (region.id !== drag.id) return region;
          const next = { ...region };
          if (drag.handle.includes("w")) next.x0 = snapX;
          if (drag.handle.includes("e")) next.x1 = snapX;
          if (drag.handle.includes("n")) next.y0 = snapY;
          if (drag.handle.includes("s")) next.y1 = snapY;
          return next;
        })
      );
    }
  };

  const onPointerUp = () => {
    panStart.current = null;
    if (drag.type === "draw" && draft) {
      const rect = normRect(draft);
      // A click without a drag would create a zero-size region; drop it.
      if (rect.w > 0.005 && rect.h > 0.005) {
        onChange([...regions, draft]);
        onSelect(draft.id);
      }
      setDraft(null);
    }
    setDrag({ type: "none" });
  };

  const handles = (region: Region) => {
    const rect = normRect(region);
    return [
      { id: "nw", x: rect.x, y: rect.y },
      { id: "n", x: rect.x + rect.w / 2, y: rect.y },
      { id: "ne", x: rect.x + rect.w, y: rect.y },
      { id: "e", x: rect.x + rect.w, y: rect.y + rect.h / 2 },
      { id: "se", x: rect.x + rect.w, y: rect.y + rect.h },
      { id: "s", x: rect.x + rect.w / 2, y: rect.y + rect.h },
      { id: "sw", x: rect.x, y: rect.y + rect.h },
      { id: "w", x: rect.x, y: rect.y + rect.h / 2 },
    ];
  };

  const startResize = (event: React.PointerEvent, id: string, handle: string) => {
    event.stopPropagation();
    onSelect(id);
    setDrag({ type: "resize", id, handle });
  };

  return (
    <div className="canvas-wrap">
      <div className="canvas-toolbar">
        <span className="hint">
          Draw: drag on empty canvas · Move: drag a region · Resize: handles ·
          Nudge: arrows (Shift = ×5) · Delete: Del · Pan: hold Space + drag
        </span>
        <span className="zoom-controls">
          <button type="button" onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}>
            −
          </button>
          <span>{Math.round(zoom * 100)}%</span>
          <button type="button" onClick={() => setZoom((z) => Math.min(4, z + 0.25))}>
            +
          </button>
          <button type="button" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}>
            Reset
          </button>
        </span>
      </div>
      <div
        ref={containerRef}
        className={`canvas-viewport ${spaceDown ? "panning" : ""}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <div
          className="canvas-inner"
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: "top left",
          }}
        >
          <img src={imageUrl} alt="Page" draggable={false} />
          <svg
            className="region-overlay"
            viewBox="0 0 1 1"
            preserveAspectRatio="none"
          >
            {/* detected page lines, faint */}
            {colLines.map((line, index) => (
              <line
                key={`cl${index}`}
                x1={line}
                y1={0}
                x2={line}
                y2={1}
                stroke="#4da3ff"
                strokeOpacity={0.15}
                strokeWidth={0.001}
              />
            ))}
            {rowLines.map((line, index) => (
              <line
                key={`rl${index}`}
                x1={0}
                y1={line}
                x2={1}
                y2={line}
                stroke="#4da3ff"
                strokeOpacity={0.15}
                strokeWidth={0.001}
              />
            ))}

            {regions.map((region) => {
              const rect = normRect(region);
              const color = REGION_KIND_COLORS[region.kind];
              const selected = region.id === selectedId;
              return (
                <g key={region.id}>
                  <rect
                    x={rect.x}
                    y={rect.y}
                    width={rect.w}
                    height={rect.h}
                    fill={color}
                    fillOpacity={selected ? 0.18 : 0.08}
                    stroke={color}
                    strokeWidth={selected ? 0.004 : 0.002}
                  />
                  <text
                    x={rect.x + 0.004}
                    y={Math.max(rect.y + 0.018, 0.02)}
                    fill={color}
                    fontSize={0.016}
                    style={{ pointerEvents: "none" }}
                  >
                    {region.name}
                  </text>
                  {selected &&
                    handles(region).map((handle) => (
                      <rect
                        key={handle.id}
                        x={handle.x - 0.004}
                        y={handle.y - 0.004}
                        width={0.008}
                        height={0.008}
                        fill={color}
                        style={{ cursor: `${handle.id}-resize` }}
                        onPointerDown={(event) =>
                          startResize(event, region.id, handle.id)
                        }
                      />
                    ))}
                </g>
              );
            })}

            {draft && (
              <rect
                {...(() => {
                  const rect = normRect(draft);
                  return {
                    x: rect.x,
                    y: rect.y,
                    width: rect.w,
                    height: rect.h,
                  };
                })()}
                fill={REGION_KIND_COLORS[draft.kind]}
                fillOpacity={0.15}
                stroke={REGION_KIND_COLORS[draft.kind]}
                strokeWidth={0.003}
                strokeDasharray="0.01 0.006"
              />
            )}
          </svg>
        </div>
      </div>
    </div>
  );
}
