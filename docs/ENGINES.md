# Engine roster

60 engines, five tiers. Generated from `backend/app/engines/registry.py`, which
is the single source of truth — if this table and the code disagree, the code
wins.

**Tier key**

| Tier | Meaning | Runs on Railway |
| --- | --- | --- |
| 1 | Core CPU, no key, default image | Yes |
| 2 | Heavy CPU (torch/paddle), `INSTALL_HEAVY=true` | Only with the heavy image |
| 3 | Cloud API with a usable free tier | Yes, with a key |
| 4 | Cloud API, paid | Yes, with a key |
| 5 | GPU-only model | **No** — Railway has no GPUs |

---

## Tier 1 — Core CPU (17)

Installed in the default image. No API key, no GPU.

| ID | Engine | Vendor | Kind | License | Notes |
| --- | --- | --- | --- | --- | --- |
| `pymupdf-text` | PyMuPDF | Artifex | text-layer | AGPL-3.0 | Fastest raw text dump; baseline for born-digital |
| `pdfplumber-text` | pdfplumber | jsvine | text-layer | MIT | Slower, but keeps word positions |
| `pypdf-text` | pypdf | pypdf | text-layer | BSD-3-Clause | Pure Python portability control |
| `pdfminer-text` | pdfminer.six | pdfminer | text-layer | MIT | Layout-aware column ordering |
| `poppler-pdftotext` | pdftotext | Poppler | text-layer | GPL-2.0 | Classic CLI; `-layout` preserves arrangement |
| `mupdf-mutool` | mutool draw | Artifex | text-layer | AGPL-3.0 | MuPDF CLI; occasionally differs from the binding |
| `tesseract-psm3` | Tesseract 5 | tesseract-ocr | OCR | Apache-2.0 | Default auto segmentation |
| `tesseract-psm11` | Tesseract 5 | tesseract-ocr | OCR | Apache-2.0 | **Sparse text — usually best for schematics** |
| `tesseract-psm12` | Tesseract 5 | tesseract-ocr | OCR | Apache-2.0 | Sparse + orientation detection |
| `rapidocr` | RapidOCR | RapidAI | OCR | Apache-2.0 | PP-OCRv4 on ONNX; best CPU OCR value |
| `docling` | Docling | IBM / LF AI | docparse | MIT | Layout, reading order, table structure |
| `markitdown` | MarkItDown | Microsoft | docparse | MIT | Text-layer only; a useful control |
| `unstructured` | Unstructured | Unstructured.io | docparse | Apache-2.0 | Element-level output for structure scoring |
| `ocrmypdf` | OCRmyPDF | OCRmyPDF | OCR | MPL-2.0 | Deskew + cleanup + Tesseract |
| `camelot` | Camelot | Camelot | table | MIT | Lattice mode needs ruling lines |
| `img2table` | img2table | img2table | table | MIT | Works on rasterized pages |
| `pymupdf4llm` | PyMuPDF4LLM | Artifex | docparse | AGPL-3.0 | Markdown tuned for LLM ingestion |

---

## Tier 2 — Heavy CPU (14)

Requires `--build-arg INSTALL_HEAVY=true` and `INSTALL_HEAVY=true` in the
environment. Adds roughly 4 GB to the image and runs at 5–15 s/page on CPU.

| ID | Engine | Vendor | License | Notes |
| --- | --- | --- | --- | --- |
| `easyocr` | EasyOCR | JaidedAI | Apache-2.0 | CRAFT + CRNN; robust on rotated labels |
| `paddleocr` | PaddleOCR PP-OCRv5 | Baidu | Apache-2.0 | Very strong on dense small text |
| `paddleocr-structure` | PP-StructureV3 | Baidu | Apache-2.0 | Layout + tables + formulas with cell coords |
| `doctr` | docTR | Mindee / t2k | Apache-2.0 | DBNet + PARSeq; clean word boxes |
| `surya-cpu` | Surya | Datalab | Apache-2.0 code / OpenRAIL-M weights | Layout + OCR + tables in one model |
| `trocr` | TrOCR | Microsoft | MIT | Transformer line recognizer |
| `kraken` | Kraken | Kraken | Apache-2.0 | Historical documents; good on degraded scans |
| `calamari` | Calamari | Calamari | Apache-2.0 | Line-based, strong on technical fonts |
| `mmocr` | MMOCR | OpenMMLab | Apache-2.0 | Modular detector/recognizer zoo |
| `nougat` | Nougat | Meta | MIT | Academic PDFs; LaTeX math |
| `mineru-cpu` | MinerU pipeline | OpenDataLab | MinerU OSL | Full pipeline; very slow on CPU |
| `marker-cpu` | Marker (fast) | Datalab | Apache-2.0 code / OpenRAIL-M weights | Run with `--disable_ocr` to stay CPU-viable |
| `ocrad` | GNU Ocrad | GNU | GPL-3.0 | Legacy control; expect poor results |
| `gocr` | GOCR | GOCR | GPL-2.0 | Legacy control |

---

## Tier 3 — Free-tier cloud APIs (9)

Enabled when the matching key is present.

| ID | Engine | Vendor | Free tier | Cost/page | Key |
| --- | --- | --- | --- | --- | --- |
| `ocrspace-e2` | OCR.space Engine 2 | a9t9 | 25,000 req/mo, **3 pages/PDF, 1 MB cap** | $0 | `OCRSPACE_KEY` |
| `ocrspace-e3` | OCR.space Engine 3 | a9t9 | 1,000 conversions/mo (separate quota) | $0 | `OCRSPACE_KEY` |
| `google-vision` | Cloud Vision | Google | 1,000 units/mo | $0.0015 | `GOOGLE_VISION_KEY` |
| `azure-docintel-read` | Document Intelligence Read | Microsoft | F0: 500 pages/mo | $0.0015 | `AZURE_DOCINTEL_*` |
| `azure-docintel-layout` | Document Intelligence Layout | Microsoft | F0: 500 pages/mo | $0.010 | `AZURE_DOCINTEL_*` |
| `gemini-flash` | Gemini Flash | Google | Generous AI Studio tier | — | `GEMINI_KEY` |
| `openrouter-qwen3vl` | Qwen3-VL | Alibaba / OpenRouter | Free-tier models available | — | `OPENROUTER_KEY` |
| `mistral-ocr` | Mistral OCR | Mistral AI | Free tier on La Plateforme | $0.001 | `MISTRAL_KEY` |
| `llamaparse` | LlamaParse | LlamaIndex | Free credits on signup | — | `LLAMAPARSE_KEY` |

> **OCR.space caveat:** the free tier caps PDFs at 3 pages and 1 MB. The adapter
> sends page images individually and downscales to fit, so long drawings are not
> silently truncated.

---

## Tier 4 — Paid cloud APIs (10)

| ID | Engine | Vendor | Cost/page | Free tier | Key |
| --- | --- | --- | --- | --- | --- |
| `aws-textract` | Textract | Amazon | $0.0015 | 1,000 pages/mo × 3 months | `AWS_ACCESS_KEY_ID` |
| `mathpix` | Mathpix | Mathpix | $0.002 | ~1,000 pages/mo | `MATHPIX_APP_ID` |
| `datalab-chandra` | Datalab (Chandra 2) | Datalab | $0.002 | ~5,000 pages/mo (work email) | `DATALAB_KEY` |
| `deepinfra-olmocr` | olmOCR 2 | AI2 / DeepInfra | $0.0002 | — | `DEEPINFRA_KEY` |
| `openai-vision` | GPT vision | OpenAI | $0.010 | — | `OPENAI_KEY` |
| `claude-vision` | Claude vision | Anthropic | $0.012 | — | `ANTHROPIC_KEY` |
| `google-docai` | Document AI | Google | $0.0015 | — | `GOOGLE_DOCAI_PROJECT` |
| `nanonets-api` | Nanonets OCR | Nanonets | $0.005 | — | `NANONETS_KEY` |
| `mindee-api` | Mindee OCR | Mindee | $0.010 | — | `MINDEE_KEY` |
| `reducto` | Reducto | Reducto | $0.015 | — | `REDUCTO_KEY` |

`datalab-chandra` scores 85.8 on olmOCR-bench — the accuracy ceiling of the
roster. `deepinfra-olmocr` is the cheapest way to run a real document VLM.

---

## Tier 5 — GPU-only (10)

Registered so they appear in the UI with an explanation, but never executed on
Railway. See [GPU_ENGINES.md](GPU_ENGINES.md) for `vllm serve` commands.

| ID | Engine | Vendor | License | Why it matters |
| --- | --- | --- | --- | --- |
| `olmocr-local` | olmOCR 2 | AI2 | Apache-2.0 | 7B VLM, ~12 GB VRAM |
| `chandra-local` | Chandra 2 | Datalab | Apache-2.0 / OpenRAIL-M | Top open-weight olmOCR score |
| `dots-mocr-local` | dots.mocr | rednote-hilab | MIT | 3B; also emits SVG for structured graphics |
| `deepseek-ocr-local` | DeepSeek-OCR | DeepSeek | MIT | Optical context compression, 3B |
| `paddleocr-vl-local` | PaddleOCR-VL | Baidu | Apache-2.0 | 0.9B; 96.3% on OmniDocBench v1.6 |
| `mineru-vlm-local` | MinerU VLM | OpenDataLab | MinerU OSL | Full-page VLM path |
| `got-ocr2` | GOT-OCR 2.0 | StepFun | Apache-2.0 | 580M unified OCR |
| `nanonets-ocr2-local` | Nanonets-OCR2 | Nanonets | **UNVERIFIED** | No LICENSE file upstream — ships disabled |
| `qwen3-vl-local` | Qwen3-VL | Alibaba | Apache-2.0 | General VLM baseline, 2B–235B |
| `internvl-ocr` | InternVL | OpenGVLab | MIT | General VLM with document strength |

---

## License summary

| License | Engines | Implication |
| --- | --- | --- |
| Apache-2.0 | Tesseract, RapidOCR, PaddleOCR, docTR, Kraken, Calamari, MMOCR, Unstructured, olmOCR, dots.mocr, DeepSeek-OCR, PaddleOCR-VL, GOT-OCR2, Qwen3-VL | Permissive |
| MIT | pdfplumber, pdfminer, Docling, MarkItDown, Camelot, img2table, TrOCR, Nougat, InternVL | Permissive |
| BSD-3-Clause | pypdf | Permissive |
| MPL-2.0 | OCRmyPDF | File-level copyleft |
| AGPL-3.0 | PyMuPDF, PyMuPDF4LLM, mupdf-tools | Network copyleft — commercial SaaS needs an Artifex license |
| GPL-2.0 / GPL-3.0 | poppler-utils, Ocrad, GOCR | Subprocess only; obligations attach to the binary |
| OpenRAIL-M | Surya, Marker (<$5M), Chandra (<$2M, no competing use) | Revenue-capped, use-restricted |
| MinerU OSL | MinerU | Apache-2.0 + attribution + 100M-MAU condition |
| Commercial SaaS | All Tier 3 and 4 APIs | Per-provider terms |
| UNVERIFIED | Nanonets-OCR2 | Do not enable until confirmed in writing |

MasterOCR invokes copyleft tools as separate processes and does not link against
them. If you redistribute or host this software, you are responsible for
complying with each engine's terms.
