# Sample corpus

The PDFs used to develop and validate MasterOCR are **not committed** — they are
customer engineering drawings and are excluded by `.gitignore`.

## What was tested

Two archives from `~/Downloads/pdf's to test`:

| Archive | Contents | Pages |
| --- | --- | --- |
| `1555-62201.zip` | Pipe spool fabrication drawings, work orders, and bills of material | ~20 PDFs |
| `pipe spool sketch pdfs.zip` | Spool sketches | varies |

## What the corpus revealed

The single most important finding, and the reason the classifier has a `vector`
category:

```
1555-SH01-6-12-4-CS.pdf
  text chars:  0
  images:      0
  drawings:    1761
```

A spool sheet with **1,761 vector paths and zero extractable characters**. The
CAD plotter (`pdfplot16.hdi`) converted every label to outlines. Any tool that
only reads the PDF text layer — PyMuPDF, pdfplumber, pypdf, pdfminer, pdftotext,
mutool, MarkItDown, PyMuPDF4LLM — returns an empty string on this file.

Only rasterize-then-OCR recovers the content. Tesseract PSM 11 extracted 572
characters, including:

```
Work Order Number:  1256899 W1
Item No             SPV0101005600600284180
Piecemark           1555-BS01-P-L-10-6-28.38-9A1A2
6" 120 (.562) PIPE A333-GR6 SMLS
3/4" PLATE A36
```

That is the whole premise of the project in one example: the "best OCR engine"
depends entirely on whether the PDF has a text layer, and for CAD exports it
usually does not.

## Reproducing

```bash
# extract
Expand-Archive "path/to/1555-62201.zip" -DestinationPath samples/set1
Expand-Archive "path/to/pipe spool sketch pdfs.zip" -DestinationPath samples/set2

# classify
cd backend
python scripts/smoke.py
```

`scripts/smoke.py` points at one specific file. Edit the `PDF` constant to test
another.

## Adding your own corpus

Drop PDFs anywhere and upload them through the UI, or point `scripts/smoke.py`
at a path. The classifier handles born-digital, raster, vector, and mixed
documents without configuration.
