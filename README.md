# MasterOCR

Compare OCR engines on PDF isometrics and schematics.

Upload a drawing, and MasterOCR runs it through every configured engine, then
shows you the results side by side with accuracy metrics, hallucination flags,
and your own star ratings.

**Live:** deploy your own on Railway (see below).

---

## Why this exists

Engineering drawings are a hostile input for OCR. They are mostly geometry, the
text is scattered rather than arranged in paragraphs, dimension callouts use
symbols (`Ø`, `R`, `±`) that general models mangle, and CAD exports frequently
convert text to vector outlines so there is no text layer at all.

That last point is the one that surprises people. In the sample corpus, a spool
sheet contains **1,761 vector paths and zero characters of extractable text** —
the labels are outlines, not glyphs. Any tool that only reads the PDF text layer
returns nothing. Only a rasterize-then-OCR pipeline recovers the content.

MasterOCR measures which engines actually handle this.

---

## What it does

1. **Classifies every page** as `born_digital`, `raster`, `vector`, or `empty`.
2. **Rasterizes** at 300 DPI so OCR engines have something to read.
3. **Runs every enabled engine** in an isolated subprocess with a hard timeout.
4. **Scores the results** against a reference and against each other.
5. **Lets you rate** each engine 1–5 stars and export everything as CSV/JSON.

### Metrics

| Metric | What it tells you |
| --- | --- |
| **CER / WER** | Character and word error rate against the reference |
| **Reference** | Text layer for born-digital pages; consensus medoid for raster/vector |
| **Missed callouts** | Dimension symbols (`Ø`, `R`, `±`, `mm`, `NPS`, `SCH`) the engine failed to read |
| **Invented callouts** | Callouts the engine produced that are not in the reference |
| **Repetition ratio** | Fraction of repeated 5-grams — catches decode loops |
| **Prose ratio** | Share of long digit-free lines — a drawing has almost none, so this is a strong VLM hallucination signal |
| **Length z-score** | Robust (MAD) outlier test on output length |
| **Garbage ratio** | Share of characters outside printable Latin ranges |
| **Table match** | Row and cell deltas versus the reference |

---

## Engine roster

60 engines across five tiers. See **[docs/ENGINES.md](docs/ENGINES.md)** for the
full table with licenses, costs, and free-tier limits.

| Tier | Count | Runs on Railway | Notes |
| --- | --- | --- | --- |
| 1 — Core CPU | 15 | Yes, default image | Text-layer extractors, Tesseract variants, RapidOCR, table tools |
| 2 — Heavy CPU | 16 | Only with `INSTALL_HEAVY=true` | torch/paddle engines incl. Docling and Unstructured; ~4 GB extra image, 5–15 s/page |
| 3 — Free API | 9 | Yes, with a key | OCR.space, Google Vision, Azure DI, Gemini, Mistral, LlamaParse |
| 4 — Paid API | 10 | Yes, with a key | Textract, Mathpix, Datalab, DeepInfra, OpenAI, Claude, Reducto |
| 5 — GPU only | 10 | **No** | Documented stubs; see [docs/GPU_ENGINES.md](docs/GPU_ENGINES.md) |

### Railway has no GPUs

This is the constraint that shapes the whole design. Railway runs CPU
containers, so GPU-only models (olmOCR, Chandra, dots.mocr, DeepSeek-OCR,
PaddleOCR-VL, MinerU-VLM, GOT-OCR2, Qwen3-VL, InternVL) cannot run here. They are
registered as Tier 5 with `requires_gpu=True`, which makes them visible in the UI
with an explanation but never executable.

To benchmark them, either use a hosted API (Datalab, DeepInfra, OpenRouter) or
run the adapters on a GPU host — the `vllm serve` commands are in
[docs/GPU_ENGINES.md](docs/GPU_ENGINES.md).

### Best performer so far

**RapidOCR** (`rapidocr`, PP-OCRv4 on ONNX Runtime) is the strongest engine on the
sample corpus. It needs no API key, no GPU, and no torch — just ONNX Runtime — and
it is the only engine that reliably recovers text from CAD plots where the labels
were converted to vector outlines.

Its cost is latency: the ONNX models are loaded per subprocess invocation, so a
single page takes roughly 30–50 s on a Railway CPU container. The registry gives
it a 600 s timeout to leave headroom for multi-page documents.

---

## Quick start

### Docker

```bash
docker build -t masterocr .
docker run -p 8000:8000 -v masterocr-data:/data masterocr
```

Open <http://localhost:8000>.

### Local development

```bash
# backend
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend (separate terminal)
cd frontend
npm install
npm run dev                   # proxies /api to :8000
```

### Tests

```bash
cd backend
python -m pytest tests -q
```

---

## Deploy to Railway

```bash
railway up
```

Railway injects `$PORT`; the container binds to it automatically. Add a volume
mounted at `/data` so results survive redeploys.

### Environment variables

Every credential is optional. An engine without its key simply reports as
unavailable rather than failing the run. Copy `.env.example` and fill in what you
have.

| Variable | Enables |
| --- | --- |
| `OCRSPACE_KEY` | `ocrspace-e2`, `ocrspace-e3` |
| `GOOGLE_VISION_KEY` | `google-vision` |
| `AZURE_DOCINTEL_ENDPOINT` + `AZURE_DOCINTEL_KEY` | `azure-docintel-read`, `azure-docintel-layout` |
| `GEMINI_KEY` | `gemini-flash` |
| `OPENROUTER_KEY` | `openrouter-qwen3vl` |
| `MISTRAL_KEY` | `mistral-ocr` |
| `LLAMAPARSE_KEY` | `llamaparse` |
| `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` | `aws-textract` |
| `MATHPIX_APP_ID` + `MATHPIX_APP_KEY` | `mathpix` |
| `DATALAB_KEY` | `datalab-chandra` |
| `DEEPINFRA_KEY` | `deepinfra-olmocr` |
| `OPENAI_KEY` | `openai-vision` |
| `ANTHROPIC_KEY` | `claude-vision` |
| `NANONETS_KEY` | `nanonets-api` |
| `MINDEE_KEY` | `mindee-api` |
| `REDUCTO_KEY` | `reducto` |

### Enabling heavy engines

```bash
docker build --build-arg INSTALL_HEAVY=true -t masterocr:heavy .
```

Then set `INSTALL_HEAVY=true` in the environment so the registry marks them
available. Expect a ~4 GB image and slow CPU inference.

Docling and Unstructured live in this tier rather than the default image: both are
CPU-capable, but they pull `torch` (and the CUDA wheels that come with it) as a
transitive dependency, which is far too large to ship by default. Unstructured's
`hi_res` strategy needs `unstructured-inference`, which requires torch.

Three heavy engines are deliberately absent from `requirements-heavy.txt` because
their pins cannot coexist with the core set — `surya-ocr` and `marker-pdf` need
`pillow<11` and `huggingface-hub>=1.5` while Docling needs `huggingface_hub<1`,
`mineru` needs `pillow>=11`, and `calamari-ocr` needs a TensorFlow build that has
no Python 3.12 wheel. Their adapters stay registered and report as unavailable
rather than breaking the build.

---

## Architecture

```
Browser ──► FastAPI ──► SQLite (/data)
                │
                ├─► rasterize.py   PyMuPDF: classify + render 300 DPI
                │
                └─► runner.py      subprocess per engine, JSON on stdin/stdout
                        │
                        ├─ engines/tesseract-psm11/run.py
                        ├─ engines/docling/run.py
                        ├─ engines/azure-docintel/run.py
                        └─ ... 60 adapters
```

**Why subprocesses?** PaddleOCR can segfault, Docling can exhaust memory, and a
cloud adapter can hang on a socket. Each engine runs in its own process with a
hard timeout, so one bad engine cannot take down the request. A crash becomes a
row in the results table, not a 500.

**Why one service?** FastAPI serves the built React bundle from the same origin,
so there is no CORS configuration and no second Railway service to pay for.

### Adding an engine

1. Add an `Engine(...)` entry to `backend/app/engines/registry.py`.
2. Create `engines/<id>/run.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared import EngineResponse, PageResult, main_wrapper

ENGINE_ID = "my-engine"

def handler(request: dict) -> EngineResponse:
    pages = [
        PageResult(page=i, text="...")
        for i, _ in enumerate(request["page_images"], start=1)
    ]
    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)

if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
```

The adapter reads one JSON object from stdin and writes one to stdout. Anything
else goes to stderr, which the runner captures separately.

---

## Licensing

MasterOCR itself is MIT. The engines it orchestrates are not, and the
distinction matters:

- **AGPL-3.0** — PyMuPDF, PyMuPDF4LLM, mupdf-tools. Fine for a public repo; a
  closed-source SaaS would need a commercial Artifex license.
- **GPL** — poppler-utils, GNU Ocrad, GOCR. Invoked as subprocess binaries, so
  GPL obligations attach to the binary rather than to MasterOCR's code.
- **OpenRAIL-M weights** — Surya and Marker (free under $5M revenue), Chandra
  (free under $2M, and may not compete with Datalab's API).
- **MinerU Open Source License** — Apache-2.0 plus attribution and a 100M-MAU
  condition.
- **Unverified** — Nanonets-OCR2 publishes no LICENSE file. It ships disabled.

See [docs/ENGINES.md](docs/ENGINES.md) for the per-engine table.

---

## Limits

- 50 MB upload, first 25 pages processed (both configurable).
- Results are retained for 72 hours by default. An hourly sweep deletes expired
  documents from SQLite and removes their upload and page images from the
  volume, so storage stays bounded without a cron service.
- No authentication. Anyone with the URL can upload and run engines, which costs
  money if paid API keys are configured. Put it behind a proxy or keep paid keys
  off a public deployment.
- Free-tier API quotas are not yet enforced by a ledger — the `quota` table
  exists but is unused. Exhausting a free tier surfaces as an engine error.
