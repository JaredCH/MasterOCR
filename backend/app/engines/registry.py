"""Declarative catalog of every OCR engine MasterOCR knows about.

This module is the single source of truth. The API, the runner, the docs
generator, and the frontend all read from `ENGINES`.

Tiers
-----
1  Core CPU, no API key, installed in the default image.
2  Heavy CPU (torch/paddle). Requires INSTALL_HEAVY=true at build time.
3  Cloud API with a usable free tier. Enabled when its key is present.
4  Cloud API, paid only. Enabled when its key is present.
5  GPU-only models. Documented but never executed on Railway (no GPUs).

License values are the *effective* terms for the component we actually ship or
call. Where code and model weights differ, both are recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Tier = Literal[1, 2, 3, 4, 5]
Kind = Literal["text-layer", "ocr", "docparse", "table", "vlm-api", "vlm-local"]
Output = Literal["text", "markdown", "html", "json"]


@dataclass(frozen=True)
class Engine:
    id: str
    name: str
    vendor: str
    tier: Tier
    kind: Kind
    license: str
    license_note: str
    output: Output
    timeout_s: int = 180
    cost_per_page_usd: float = 0.0
    free_tier: str | None = None
    requires_key: str | None = None
    requires_gpu: bool = False
    requires_heavy: bool = False
    enabled_by_default: bool = True
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def runnable_on_railway(self) -> bool:
        """Railway is CPU-only, so GPU engines can never run here."""
        return not self.requires_gpu


# ---------------------------------------------------------------------------
# Tier 1 — core CPU engines, no key, default image
# ---------------------------------------------------------------------------

_TIER1: list[Engine] = [
    # --- raw text-layer extractors ------------------------------------
    Engine(
        id="pymupdf-text",
        name="PyMuPDF (text layer)",
        vendor="Artifex",
        tier=1,
        kind="text-layer",
        license="AGPL-3.0",
        license_note="AGPL applies to the library; we call it in-process. Fine for a public repo, "
        "but a closed-source SaaS would need a commercial Artifex license.",
        output="text",
        timeout_s=60,
        notes="Fastest raw text dump. Baseline for born-digital CAD exports.",
        tags=("baseline", "fast"),
    ),
    Engine(
        id="pdfplumber-text",
        name="pdfplumber (text layer)",
        vendor="jsvine",
        tier=1,
        kind="text-layer",
        license="MIT",
        license_note="Permissive.",
        output="text",
        timeout_s=90,
        notes="Slower than PyMuPDF but preserves word positions, which helps dimension callouts.",
        tags=("baseline", "positions"),
    ),
    Engine(
        id="pypdf-text",
        name="pypdf (text layer)",
        vendor="pypdf",
        tier=1,
        kind="text-layer",
        license="BSD-3-Clause",
        license_note="Permissive.",
        output="text",
        timeout_s=90,
        notes="Pure Python, no native deps. Useful as a portability control.",
        tags=("baseline",),
    ),
    Engine(
        id="pdfminer-text",
        name="pdfminer.six (text layer)",
        vendor="pdfminer",
        tier=1,
        kind="text-layer",
        license="MIT",
        license_note="Permissive.",
        output="text",
        timeout_s=120,
        notes="Layout-aware text extraction; good at column ordering.",
        tags=("baseline", "layout"),
    ),
    Engine(
        id="poppler-pdftotext",
        name="pdftotext (poppler)",
        vendor="Poppler",
        tier=1,
        kind="text-layer",
        license="GPL-2.0",
        license_note="Invoked as a subprocess binary, not linked. GPL obligations attach to the "
        "binary, not to MasterOCR's Python code.",
        output="text",
        timeout_s=60,
        notes="The classic CLI baseline. -layout mode preserves spatial arrangement.",
        tags=("baseline", "cli"),
    ),
    Engine(
        id="mupdf-mutool",
        name="mutool draw -F txt",
        vendor="Artifex",
        tier=1,
        kind="text-layer",
        license="AGPL-3.0",
        license_note="Subprocess binary. Same AGPL consideration as PyMuPDF.",
        output="text",
        timeout_s=60,
        notes="MuPDF's own CLI; occasionally differs from the Python binding.",
        tags=("baseline", "cli"),
    ),
    # --- Tesseract page-segmentation variants -------------------------
    Engine(
        id="tesseract-psm3",
        name="Tesseract 5 (PSM 3, auto)",
        vendor="tesseract-ocr",
        tier=1,
        kind="ocr",
        license="Apache-2.0",
        license_note="Fully permissive, including traineddata.",
        output="text",
        timeout_s=180,
        notes="Default auto page segmentation. The reference CPU OCR baseline.",
        tags=("ocr", "baseline"),
    ),
    Engine(
        id="tesseract-psm11",
        name="Tesseract 5 (PSM 11, sparse text)",
        vendor="tesseract-ocr",
        tier=1,
        kind="ocr",
        license="Apache-2.0",
        license_note="Fully permissive.",
        output="text",
        timeout_s=180,
        notes="Sparse-text mode. Usually the best Tesseract setting for isometrics and "
        "schematics, where labels are scattered rather than in paragraphs.",
        tags=("ocr", "schematics"),
    ),
    Engine(
        id="tesseract-psm12",
        name="Tesseract 5 (PSM 12, sparse + OSD)",
        vendor="tesseract-ocr",
        tier=1,
        kind="ocr",
        license="Apache-2.0",
        license_note="Fully permissive.",
        output="text",
        timeout_s=180,
        notes="Sparse text with orientation detection. Handles rotated drawing labels.",
        tags=("ocr", "schematics", "rotation"),
    ),
    # --- modern CPU OCR ------------------------------------------------
    Engine(
        id="rapidocr",
        name="RapidOCR (PP-OCRv4 ONNX)",
        vendor="RapidAI",
        tier=1,
        kind="ocr",
        license="Apache-2.0",
        license_note="Permissive; ONNX models derived from PaddleOCR (also Apache-2.0).",
        output="text",
        timeout_s=180,
        notes="PaddleOCR accuracy without the Paddle runtime. Best CPU OCR value in the roster.",
        tags=("ocr", "onnx", "recommended"),
    ),
    # --- document parsers ----------------------------------------------
    Engine(
        id="docling",
        name="Docling",
        vendor="IBM / LF AI & Data",
        tier=1,
        kind="docparse",
        license="MIT",
        license_note="Code MIT. Bundled layout/table models are permissive; GraniteDocling VLM "
        "weights are Apache-2.0.",
        output="markdown",
        timeout_s=300,
        notes="Strong layout + reading order + table structure. CPU-capable default pipeline.",
        tags=("docparse", "layout", "tables", "recommended"),
    ),
    Engine(
        id="markitdown",
        name="MarkItDown",
        vendor="Microsoft",
        tier=1,
        kind="docparse",
        license="MIT",
        license_note="Permissive.",
        output="markdown",
        timeout_s=120,
        notes="Lightweight PDF-to-Markdown. No OCR by default — a useful control showing what "
        "the text layer alone yields.",
        tags=("docparse", "markdown"),
    ),
    Engine(
        id="unstructured",
        name="Unstructured (hi_res)",
        vendor="Unstructured.io",
        tier=1,
        kind="docparse",
        license="Apache-2.0",
        license_note="Permissive. hi_res strategy pulls in detectron2/YOLOX layout weights "
        "(Apache-2.0).",
        output="json",
        timeout_s=300,
        notes="Element-level output (Title, Table, NarrativeText) — good for structure scoring.",
        tags=("docparse", "elements"),
    ),
    Engine(
        id="ocrmypdf",
        name="OCRmyPDF",
        vendor="OCRmyPDF",
        tier=1,
        kind="ocr",
        license="MPL-2.0",
        license_note="MPL is file-level copyleft; we call the CLI. Bundles Tesseract (Apache-2.0).",
        output="text",
        timeout_s=300,
        notes="Produces a searchable PDF, then we extract its text layer. Includes deskew and "
        "cleanup, which helps scanned drawings.",
        tags=("ocr", "preprocess", "searchable-pdf"),
    ),
    # --- table extractors ----------------------------------------------
    Engine(
        id="camelot",
        name="Camelot (lattice/stream)",
        vendor="Camelot",
        tier=1,
        kind="table",
        license="MIT",
        license_note="Permissive.",
        output="json",
        timeout_s=180,
        notes="Table-only. Lattice mode needs ruling lines — common on BOM tables in drawings.",
        tags=("tables",),
    ),
    Engine(
        id="img2table",
        name="img2table",
        vendor="img2table",
        tier=1,
        kind="table",
        license="MIT",
        license_note="Permissive.",
        output="json",
        timeout_s=180,
        notes="Image-based table detection; works on rasterized pages where Camelot cannot.",
        tags=("tables", "raster"),
    ),
    Engine(
        id="pymupdf4llm",
        name="PyMuPDF4LLM",
        vendor="Artifex",
        tier=1,
        kind="docparse",
        license="AGPL-3.0",
        license_note="Same AGPL consideration as PyMuPDF.",
        output="markdown",
        timeout_s=120,
        notes="Markdown tuned for LLM ingestion. Fast, text-layer only.",
        tags=("docparse", "markdown", "fast"),
    ),
]


# ---------------------------------------------------------------------------
# Tier 2 — heavy CPU engines (torch / paddle), opt-in at build time
# ---------------------------------------------------------------------------

_TIER2: list[Engine] = [
    Engine(
        id="easyocr",
        name="EasyOCR",
        vendor="JaidedAI",
        tier=2,
        kind="ocr",
        license="Apache-2.0",
        license_note="Permissive.",
        output="text",
        timeout_s=300,
        requires_heavy=True,
        notes="CRAFT detector + CRNN recognizer. Robust on rotated and low-contrast labels.",
        tags=("ocr", "torch"),
    ),
    Engine(
        id="paddleocr",
        name="PaddleOCR (PP-OCRv5)",
        vendor="Baidu",
        tier=2,
        kind="ocr",
        license="Apache-2.0",
        license_note="Permissive.",
        output="text",
        timeout_s=300,
        requires_heavy=True,
        notes="Very strong on dense small text. Heavy Paddle runtime.",
        tags=("ocr", "paddle", "recommended"),
    ),
    Engine(
        id="paddleocr-structure",
        name="PaddleOCR PP-StructureV3",
        vendor="Baidu",
        tier=2,
        kind="docparse",
        license="Apache-2.0",
        license_note="Permissive.",
        output="markdown",
        timeout_s=420,
        requires_heavy=True,
        notes="Layout + tables + formulas with cell-level coordinates.",
        tags=("docparse", "layout", "tables", "paddle"),
    ),
    Engine(
        id="doctr",
        name="docTR",
        vendor="Mindee / t2k",
        tier=2,
        kind="ocr",
        license="Apache-2.0",
        license_note="Permissive.",
        output="text",
        timeout_s=300,
        requires_heavy=True,
        notes="DBNet + PARSeq. Clean word-level boxes and confidences.",
        tags=("ocr", "torch", "positions"),
    ),
    Engine(
        id="surya-cpu",
        name="Surya (CPU)",
        vendor="Datalab",
        tier=2,
        kind="ocr",
        license="Apache-2.0 code / OpenRAIL-M weights",
        license_note="Code is Apache-2.0. Weights are modified OpenRAIL-M: free for research, "
        "personal use, and companies under $5M funding/revenue. Above that, a Datalab "
        "commercial license is required.",
        output="markdown",
        timeout_s=420,
        requires_heavy=True,
        notes="Layout + OCR + tables in one model. CPU inference is slow but works.",
        tags=("ocr", "layout", "tables", "openrail"),
    ),
    Engine(
        id="trocr",
        name="TrOCR (printed)",
        vendor="Microsoft",
        tier=2,
        kind="ocr",
        license="MIT",
        license_note="Permissive.",
        output="text",
        timeout_s=300,
        requires_heavy=True,
        notes="Transformer line recognizer. Needs an external detector; we pair it with "
        "Tesseract's line boxes.",
        tags=("ocr", "torch", "line-level"),
    ),
    Engine(
        id="kraken",
        name="Kraken",
        vendor="Kraken",
        tier=2,
        kind="ocr",
        license="Apache-2.0",
        license_note="Permissive.",
        output="text",
        timeout_s=300,
        requires_heavy=True,
        notes="Historical-document OCR. Surprisingly good on degraded scans.",
        tags=("ocr", "torch", "historical"),
    ),
    Engine(
        id="calamari",
        name="Calamari OCR",
        vendor="Calamari",
        tier=2,
        kind="ocr",
        license="Apache-2.0",
        license_note="Permissive.",
        output="text",
        timeout_s=300,
        requires_heavy=True,
        notes="Line-based, fast on clean print. Strong on technical fonts.",
        tags=("ocr", "torch"),
    ),
    Engine(
        id="mmocr",
        name="MMOCR",
        vendor="OpenMMLab",
        tier=2,
        kind="ocr",
        license="Apache-2.0",
        license_note="Permissive.",
        output="text",
        timeout_s=360,
        requires_heavy=True,
        notes="Modular detector/recognizer zoo. Useful for comparing architectures.",
        tags=("ocr", "torch"),
    ),
    Engine(
        id="nougat",
        name="Nougat",
        vendor="Meta",
        tier=2,
        kind="docparse",
        license="MIT",
        license_note="Permissive.",
        output="markdown",
        timeout_s=420,
        requires_heavy=True,
        notes="Academic-PDF specialist. LaTeX math output; weak on drawings.",
        tags=("docparse", "math"),
    ),
    Engine(
        id="mineru-cpu",
        name="MinerU (CPU pipeline)",
        vendor="OpenDataLab",
        tier=2,
        kind="docparse",
        license="MinerU Open Source License",
        license_note="Apache-2.0 plus conditions: attribution required, and services exceeding "
        "100M monthly active users need a separate commercial license.",
        output="markdown",
        timeout_s=600,
        requires_heavy=True,
        notes="Full document pipeline. Very slow on CPU but high structural fidelity.",
        tags=("docparse", "layout", "tables"),
    ),
    Engine(
        id="marker-cpu",
        name="Marker (CPU, fast mode)",
        vendor="Datalab",
        tier=2,
        kind="docparse",
        license="Apache-2.0 code / OpenRAIL-M weights",
        license_note="Code Apache-2.0. Weights are modified OpenRAIL-M: free for research, "
        "personal use, and companies under $5M funding/revenue.",
        output="markdown",
        timeout_s=600,
        requires_heavy=True,
        notes="Run with --mode fast --disable_ocr to stay CPU-viable.",
        tags=("docparse", "markdown", "openrail"),
    ),
    Engine(
        id="ocrad",
        name="GNU Ocrad",
        vendor="GNU",
        tier=2,
        kind="ocr",
        license="GPL-3.0",
        license_note="Subprocess binary. GPL obligations attach to the binary.",
        output="text",
        timeout_s=120,
        requires_heavy=True,
        notes="Legacy engine. Included as a historical control — expect poor results.",
        tags=("ocr", "cli", "legacy"),
    ),
    Engine(
        id="gocr",
        name="GOCR",
        vendor="GOCR",
        tier=2,
        kind="ocr",
        license="GPL-2.0",
        license_note="Subprocess binary.",
        output="text",
        timeout_s=120,
        requires_heavy=True,
        notes="Legacy engine. Historical control.",
        tags=("ocr", "cli", "legacy"),
    ),
]


# ---------------------------------------------------------------------------
# Tier 3 — cloud APIs with a usable free tier
# ---------------------------------------------------------------------------

_TIER3: list[Engine] = [
    Engine(
        id="ocrspace-e2",
        name="OCR.space Engine 2",
        vendor="a9t9",
        tier=3,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service. Free tier is rate-limited per IP.",
        output="text",
        timeout_s=120,
        cost_per_page_usd=0.0,
        free_tier="25,000 requests/month, but 3 pages per PDF and 1 MB file cap",
        requires_key="ocrspace_key",
        notes="Cheap and fast. The 3-page cap means we chunk long drawings.",
        tags=("api", "free"),
    ),
    Engine(
        id="ocrspace-e3",
        name="OCR.space Engine 3",
        vendor="a9t9",
        tier=3,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service.",
        output="markdown",
        timeout_s=180,
        free_tier="1,000 Engine-3 conversions/month (separate quota)",
        requires_key="ocrspace_key",
        notes="Newest engine: 200+ languages, table recognition, Markdown output.",
        tags=("api", "free", "tables"),
    ),
    Engine(
        id="google-vision",
        name="Google Cloud Vision (DOCUMENT_TEXT_DETECTION)",
        vendor="Google",
        tier=3,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service.",
        output="text",
        timeout_s=120,
        cost_per_page_usd=0.0015,
        free_tier="1,000 units/month free, then $1.50 per 1,000",
        requires_key="google_vision_key",
        notes="Strong dense-text detection. Word-level boxes included.",
        tags=("api", "free", "positions"),
    ),
    Engine(
        id="azure-docintel-read",
        name="Azure Document Intelligence (Read)",
        vendor="Microsoft",
        tier=3,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service.",
        output="text",
        timeout_s=180,
        cost_per_page_usd=0.0015,
        free_tier="F0 tier: 500 pages/month free",
        requires_key="azure_docintel_key",
        notes="prebuilt-read model. Excellent on rotated and low-quality scans.",
        tags=("api", "free", "recommended"),
    ),
    Engine(
        id="azure-docintel-layout",
        name="Azure Document Intelligence (Layout)",
        vendor="Microsoft",
        tier=3,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service.",
        output="markdown",
        timeout_s=240,
        cost_per_page_usd=0.010,
        free_tier="F0 tier: 500 pages/month free",
        requires_key="azure_docintel_key",
        notes="prebuilt-layout: tables, selection marks, paragraph structure.",
        tags=("api", "free", "tables", "layout"),
    ),
    Engine(
        id="gemini-flash",
        name="Gemini Flash (vision)",
        vendor="Google",
        tier=3,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service.",
        output="markdown",
        timeout_s=180,
        free_tier="Generous free tier via AI Studio",
        requires_key="gemini_key",
        notes="General VLM prompted to transcribe. Strong on messy drawings, but prone to "
        "inventing plausible labels — the hallucination metrics matter here.",
        tags=("api", "free", "vlm"),
    ),
    Engine(
        id="openrouter-qwen3vl",
        name="Qwen3-VL via OpenRouter",
        vendor="Alibaba / OpenRouter",
        tier=3,
        kind="vlm-api",
        license="Commercial SaaS (model: Apache-2.0)",
        license_note="Qwen3-VL weights are Apache-2.0; OpenRouter is a paid gateway with some "
        "free-tier models.",
        output="markdown",
        timeout_s=240,
        free_tier="Free-tier models available on OpenRouter",
        requires_key="openrouter_key",
        notes="Open-weight VLM through a single API. Good open-vs-closed comparison.",
        tags=("api", "free", "vlm", "open-weights"),
    ),
    Engine(
        id="mistral-ocr",
        name="Mistral OCR",
        vendor="Mistral AI",
        tier=3,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service.",
        output="markdown",
        timeout_s=180,
        cost_per_page_usd=0.001,
        free_tier="Free tier available on La Plateforme",
        requires_key="mistral_key",
        notes="Document-native OCR endpoint with Markdown + bounding boxes.",
        tags=("api", "free", "positions"),
    ),
    Engine(
        id="llamaparse",
        name="LlamaParse",
        vendor="LlamaIndex",
        tier=3,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service.",
        output="markdown",
        timeout_s=300,
        free_tier="Free credits on signup (limited pages)",
        requires_key="llamaparse_key",
        notes="Agentic document parsing. Good at tables and multi-column layouts.",
        tags=("api", "free", "tables"),
    ),
]


# ---------------------------------------------------------------------------
# Tier 4 — paid cloud APIs
# ---------------------------------------------------------------------------

_TIER4: list[Engine] = [
    Engine(
        id="aws-textract",
        name="AWS Textract",
        vendor="Amazon",
        tier=4,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service.",
        output="text",
        timeout_s=180,
        cost_per_page_usd=0.0015,
        free_tier="1,000 pages/month for the first 3 months",
        requires_key="aws_access_key_id",
        notes="DetectDocumentText + AnalyzeDocument TABLES/FORMS.",
        tags=("api", "paid", "tables"),
    ),
    Engine(
        id="mathpix",
        name="Mathpix",
        vendor="Mathpix",
        tier=4,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service.",
        output="markdown",
        timeout_s=180,
        cost_per_page_usd=0.002,
        free_tier="~1,000 pages/month on the free plan",
        requires_key="mathpix_app_id",
        notes="Best-in-class math/LaTeX. Overkill for drawings but a useful upper bound.",
        tags=("api", "paid", "math"),
    ),
    Engine(
        id="datalab-chandra",
        name="Datalab API (Chandra 2)",
        vendor="Datalab",
        tier=4,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary hosted service. The open weights are OpenRAIL-M, but the API "
        "is a paid product.",
        output="markdown",
        timeout_s=240,
        cost_per_page_usd=0.002,
        free_tier="~5,000 pages/month free with a work email",
        requires_key="datalab_key",
        notes="Highest olmOCR-bench score in the roster (85.8). The accuracy ceiling.",
        tags=("api", "paid", "recommended"),
    ),
    Engine(
        id="deepinfra-olmocr",
        name="olmOCR 2 via DeepInfra",
        vendor="AI2 / DeepInfra",
        tier=4,
        kind="vlm-api",
        license="Apache-2.0 (model) / Commercial SaaS (host)",
        license_note="olmOCR code and weights are Apache-2.0. DeepInfra bills per token.",
        output="markdown",
        timeout_s=240,
        cost_per_page_usd=0.0002,
        requires_key="deepinfra_key",
        notes="Cheapest way to run a real document VLM. ~$0.09/M input tokens.",
        tags=("api", "paid", "open-weights", "cheap"),
    ),
    Engine(
        id="openai-vision",
        name="OpenAI GPT vision",
        vendor="OpenAI",
        tier=4,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service.",
        output="markdown",
        timeout_s=240,
        cost_per_page_usd=0.010,
        requires_key="openai_key",
        notes="General VLM transcription. Included to measure generalist-VLM hallucination.",
        tags=("api", "paid", "vlm"),
    ),
    Engine(
        id="claude-vision",
        name="Anthropic Claude vision",
        vendor="Anthropic",
        tier=4,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service.",
        output="markdown",
        timeout_s=240,
        cost_per_page_usd=0.012,
        requires_key="anthropic_key",
        notes="General VLM transcription. Strong instruction-following on output format.",
        tags=("api", "paid", "vlm"),
    ),
    Engine(
        id="google-docai",
        name="Google Document AI (OCR)",
        vendor="Google",
        tier=4,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service.",
        output="text",
        timeout_s=180,
        cost_per_page_usd=0.0015,
        requires_key="google_docai_project",
        notes="Enterprise document OCR processor. Distinct from Cloud Vision.",
        tags=("api", "paid"),
    ),
    Engine(
        id="nanonets-api",
        name="Nanonets OCR API",
        vendor="Nanonets",
        tier=4,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service.",
        output="markdown",
        timeout_s=240,
        cost_per_page_usd=0.005,
        requires_key="nanonets_key",
        notes="Hosted version of their OCR-2 model, which emits structured Markdown.",
        tags=("api", "paid"),
    ),
    Engine(
        id="mindee-api",
        name="Mindee OCR",
        vendor="Mindee",
        tier=4,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service.",
        output="text",
        timeout_s=180,
        cost_per_page_usd=0.010,
        requires_key="mindee_key",
        notes="Document-specific models plus a generic OCR endpoint.",
        tags=("api", "paid"),
    ),
    Engine(
        id="reducto",
        name="Reducto",
        vendor="Reducto",
        tier=4,
        kind="vlm-api",
        license="Commercial SaaS",
        license_note="Proprietary service.",
        output="markdown",
        timeout_s=240,
        cost_per_page_usd=0.015,
        requires_key="reducto_key",
        notes="Agentic parsing with strong table and figure handling.",
        tags=("api", "paid", "tables"),
    ),
]


# ---------------------------------------------------------------------------
# Tier 5 — GPU-only models. Documented, never executed on Railway.
# ---------------------------------------------------------------------------

_TIER5: list[Engine] = [
    Engine(
        id="olmocr-local",
        name="olmOCR 2 (local)",
        vendor="AI2",
        tier=5,
        kind="vlm-local",
        license="Apache-2.0",
        license_note="Fully permissive, including weights.",
        output="markdown",
        requires_gpu=True,
        enabled_by_default=False,
        notes="7B VLM. Needs ~12 GB VRAM. Run via vLLM on a GPU host.",
        tags=("gpu", "vlm"),
    ),
    Engine(
        id="chandra-local",
        name="Chandra 2 (local)",
        vendor="Datalab",
        tier=5,
        kind="vlm-local",
        license="Apache-2.0 code / OpenRAIL-M weights",
        license_note="Weights are OpenRAIL-M: free under $2M revenue, and may not be used to "
        "compete with Datalab's API.",
        output="markdown",
        requires_gpu=True,
        enabled_by_default=False,
        notes="Top olmOCR-bench score among open weights. Needs a GPU.",
        tags=("gpu", "vlm", "openrail"),
    ),
    Engine(
        id="dots-mocr-local",
        name="dots.mocr (local)",
        vendor="rednote-hilab",
        tier=5,
        kind="vlm-local",
        license="MIT",
        license_note="Permissive.",
        output="markdown",
        requires_gpu=True,
        enabled_by_default=False,
        notes="3B multilingual parser. Also emits SVG for structured graphics — interesting for "
        "schematics.",
        tags=("gpu", "vlm", "svg"),
    ),
    Engine(
        id="deepseek-ocr-local",
        name="DeepSeek-OCR (local)",
        vendor="DeepSeek",
        tier=5,
        kind="vlm-local",
        license="MIT",
        license_note="Permissive.",
        output="markdown",
        requires_gpu=True,
        enabled_by_default=False,
        notes="Optical context compression. 3B, runs on a modest GPU.",
        tags=("gpu", "vlm"),
    ),
    Engine(
        id="paddleocr-vl-local",
        name="PaddleOCR-VL (local)",
        vendor="Baidu",
        tier=5,
        kind="vlm-local",
        license="Apache-2.0",
        license_note="Permissive.",
        output="markdown",
        requires_gpu=True,
        enabled_by_default=False,
        notes="0.9B VLM. 96.3% on OmniDocBench v1.6 — best accuracy-per-parameter available.",
        tags=("gpu", "vlm", "recommended"),
    ),
    Engine(
        id="mineru-vlm-local",
        name="MinerU VLM backend (local)",
        vendor="OpenDataLab",
        tier=5,
        kind="vlm-local",
        license="MinerU Open Source License",
        license_note="Apache-2.0 plus attribution and 100M-MAU conditions.",
        output="markdown",
        requires_gpu=True,
        enabled_by_default=False,
        notes="MinerU's full-page VLM path, distinct from its CPU pipeline.",
        tags=("gpu", "vlm"),
    ),
    Engine(
        id="got-ocr2",
        name="GOT-OCR 2.0",
        vendor="StepFun",
        tier=5,
        kind="vlm-local",
        license="Apache-2.0",
        license_note="Permissive.",
        output="markdown",
        requires_gpu=True,
        enabled_by_default=False,
        notes="580M unified OCR model. Handles formulas and charts.",
        tags=("gpu", "vlm"),
    ),
    Engine(
        id="nanonets-ocr2-local",
        name="Nanonets-OCR2 (local)",
        vendor="Nanonets",
        tier=5,
        kind="vlm-local",
        license="UNVERIFIED",
        license_note="The upstream repo publishes no LICENSE file. Do not enable until the "
        "weight license is confirmed in writing.",
        output="markdown",
        requires_gpu=True,
        enabled_by_default=False,
        notes="3B model with LaTeX/table/checkbox output. License must be confirmed first.",
        tags=("gpu", "vlm", "license-risk"),
    ),
    Engine(
        id="qwen3-vl-local",
        name="Qwen3-VL (local)",
        vendor="Alibaba",
        tier=5,
        kind="vlm-local",
        license="Apache-2.0",
        license_note="Permissive.",
        output="markdown",
        requires_gpu=True,
        enabled_by_default=False,
        notes="General VLM baseline. Sizes from 2B to 235B.",
        tags=("gpu", "vlm"),
    ),
    Engine(
        id="internvl-ocr",
        name="InternVL (local)",
        vendor="OpenGVLab",
        tier=5,
        kind="vlm-local",
        license="MIT",
        license_note="Permissive.",
        output="markdown",
        requires_gpu=True,
        enabled_by_default=False,
        notes="General VLM with strong document understanding.",
        tags=("gpu", "vlm"),
    ),
]


ENGINES: list[Engine] = [*_TIER1, *_TIER2, *_TIER3, *_TIER4, *_TIER5]

ENGINES_BY_ID: dict[str, Engine] = {engine.id: engine for engine in ENGINES}


def get_engine(engine_id: str) -> Engine:
    try:
        return ENGINES_BY_ID[engine_id]
    except KeyError as exc:
        raise KeyError(f"Unknown engine id: {engine_id}") from exc


def tier_counts() -> dict[int, int]:
    counts: dict[int, int] = {}
    for engine in ENGINES:
        counts[engine.tier] = counts.get(engine.tier, 0) + 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":  # pragma: no cover - manual inspection helper
    print(f"{len(ENGINES)} engines registered")
    for tier, count in tier_counts().items():
        print(f"  tier {tier}: {count}")
