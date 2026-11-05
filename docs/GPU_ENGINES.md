# GPU-only engines

Railway runs CPU containers, so none of these can execute on the deployed app.
They are registered as Tier 5 with `requires_gpu=True`, which makes them visible
in the UI with an explanation but never runnable.

This document exists so the roster is complete and so you can benchmark them
elsewhere without re-deriving the setup.

---

## Why they are excluded

| Constraint | Detail |
| --- | --- |
| Railway has no GPU instances | Containers are CPU-only. Hobby caps at 48 vCPU / 48 GB per service. |
| Model sizes | 0.9B–7B parameters; the 7B models need ~12–16 GB VRAM. |
| Inference servers | Most expect vLLM or llama.cpp, which need CUDA. |

## How to run them anyway

Three options, in order of effort:

1. **Hosted API** — Datalab (Chandra), DeepInfra (olmOCR), OpenRouter (Qwen3-VL).
   These are already wired up as Tier 3/4 engines. Zero infrastructure.
2. **GPU host** — RunPod, Modal, or any CUDA box. Run the `vllm serve` command
   below, then point a new adapter at the OpenAI-compatible endpoint.
3. **Local GPU** — same commands, on your own machine.

---

## Serving commands

### olmOCR 2 (AI2) — Apache-2.0

```bash
vllm serve allenai/olmOCR-2-7B-1025-FP8 --max-model-len 16384
```

Then:

```bash
olmocr ./workspace --server http://localhost:8000/v1 \
  --model allenai/olmOCR-2-7B-1025-FP8 --markdown --pdfs *.pdf
```

Needs ~12 GB VRAM. Scores 82.4 on olmOCR-bench.

### Chandra 2 (Datalab) — Apache-2.0 code / OpenRAIL-M weights

```bash
chandra_vllm          # launches a Docker container with tuned settings
chandra input.pdf ./output --method vllm
```

Or serve directly:

```bash
vllm serve datalab-to/chandra-ocr-2
```

Scores 85.8 on olmOCR-bench — the highest open-weight result. Weights are
OpenRAIL-M: free under $2M revenue, and may not be used to compete with
Datalab's API.

### dots.mocr (rednote-hilab) — MIT

```bash
vllm serve rednote-hilab/dots.mocr \
  --tensor-parallel-size 1 \
  --gpu-memory-utilization 0.9 \
  --chat-template-content-format string \
  --served-model-name model \
  --trust-remote-code
```

3B parameters. Uniquely, it can emit **SVG** for structured graphics — worth
testing on schematics specifically, since it may reconstruct geometry rather
than just labels.

### DeepSeek-OCR — MIT

```bash
vllm serve deepseek-ai/DeepSeek-OCR
```

3B. Uses optical context compression; supports Tiny/Small/Base/Large/Gundam
resolution modes.

### PaddleOCR-VL (Baidu) — Apache-2.0

```bash
vllm serve PaddlePaddle/PaddleOCR-VL
```

0.9B parameters, 96.3% on OmniDocBench v1.6. Best accuracy-per-parameter
available — the most interesting model to test if you have limited VRAM.

### MinerU VLM backend (OpenDataLab) — MinerU OSL

```bash
mineru -p input.pdf -o out -b vlm-vllm-engine
```

Distinct from the CPU pipeline (`mineru-cpu`, Tier 2). Requires a GPU for the
VLM path.

### GOT-OCR 2.0 (StepFun) — Apache-2.0

```bash
python -c "
from transformers import AutoModel, AutoTokenizer
model = AutoModel.from_pretrained('stepfun-ai/GOT-OCR2_0', trust_remote_code=True).cuda()
"
```

580M unified model. Handles formulas and charts.

### Qwen3-VL (Alibaba) — Apache-2.0

```bash
vllm serve Qwen/Qwen3-VL-8B-Instruct
```

General VLM baseline. Sizes from 2B to 235B.

### InternVL (OpenGVLab) — MIT

```bash
vllm serve OpenGVLab/InternVL3-8B
```

General VLM with strong document understanding.

### Nanonets-OCR2 — **LICENSE UNVERIFIED**

```bash
# DO NOT DEPLOY until the weight license is confirmed in writing.
vllm serve Nanonets/Nanonets-OCR2-3B
```

The upstream repository publishes no LICENSE file. It ships disabled in the
registry for that reason.

---

## Adding a GPU engine to MasterOCR

The adapter contract is identical to CPU engines — only the transport changes.
A GPU adapter is a thin HTTP client:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared import EngineResponse, PageResult, main_wrapper

ENGINE_ID = "olmocr-local"

def handler(request: dict) -> EngineResponse:
    import httpx
    server = request["options"].get("server", "http://localhost:8000/v1")
    pages = []
    for index, image_path in enumerate(request["page_images"], start=1):
        # POST to the OpenAI-compatible endpoint, parse the response
        ...
        pages.append(PageResult(page=index, markdown=text))
    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)

if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
```

Then flip `requires_gpu=False` in the registry entry and set
`enabled_by_default=True`. The runner will treat it like any other engine.

---

## Expected results on engineering drawings

No public benchmark covers isometrics and schematics specifically — that is the
gap this project exists to fill. Based on the olmOCR-bench categories that come
closest (tables, old scans, long tiny text), the rough ordering to expect:

| Model | Expected strength | Expected weakness |
| --- | --- | --- |
| Chandra 2 | Highest overall accuracy; strong on degraded scans | Slowest; OpenRAIL restrictions |
| PaddleOCR-VL | Best accuracy per parameter; strong on dense small text | 0.9B may struggle with sparse layouts |
| dots.mocr | Only model that can emit SVG geometry | Weaker on complex tables |
| olmOCR 2 | Strong reading order and header/footer removal | Tuned for prose documents, not drawings |
| DeepSeek-OCR | Fast, cheap, good compression | Less accurate on fine detail |
| Qwen3-VL / InternVL | Broad general capability | Hallucinate prose on non-prose pages |

The hallucination metrics in MasterOCR (prose ratio, length z-score, novel
vocabulary rate) exist specifically to catch the last row.
