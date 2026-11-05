"""End-to-end smoke test against a real drawing from the sample corpus."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.engines import registry
from app.engines.runner import is_available, run_many
from app.services import metrics, rasterize

PDF = Path(r"C:\Users\Jared\MasterOCR\samples\set1\1555-62201\1555-SH01-6-12-4-CS.pdf")


def main() -> None:
    settings = get_settings()
    work = settings.work_dir / "smoke"
    work.mkdir(parents=True, exist_ok=True)

    info = rasterize.inspect(PDF, dpi=300, output_dir=work / "pages", max_pages=1)
    images = [p.image_path for p in info.pages if p.image_path]
    print("document:", PDF.name, "->", info.classification)

    engines = [e for e in registry.ENGINES if is_available(e, settings)[0]]
    print("runnable:", [e.id for e in engines])

    outcomes = asyncio.run(
        run_many(
            engines,
            pdf_path=PDF,
            page_images=images,
            page_count=1,
            settings=settings,
        )
    )

    print("\n--- engine results ---")
    for o in outcomes:
        err = (o.error or "")[:70]
        print(f"{o.engine_id:22} ok={o.ok!s:5} {o.duration_ms:6}ms chars={len(o.text):5} {err}")

    texts = {o.engine_id: o.text for o in outcomes if o.ok and o.text.strip()}
    if not texts:
        print("\nNo engine produced text.")
        return

    report = metrics.evaluate(texts, reference_text=None, reference_name="consensus")
    print("\n--- CER ranking (consensus reference) ---")
    for engine_id, v in sorted(report.items(), key=lambda kv: kv[1]["cer"]):
        print(
            f"{engine_id:22} cer={v['cer']:.3f} words={v['word_count']:4} "
            f"missed={v['dimensions']['missed']:3} flags={v['hallucination']['flags']}"
        )


if __name__ == "__main__":
    main()
