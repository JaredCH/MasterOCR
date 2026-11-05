"""Parse engine output into a rectangular matrix of cell strings.

Whole-table engines (camelot, img2table, Azure layout, Docling) each emit a
different shape: Markdown pipe tables, HTML ``<table>``, or CSV. Cell-OCR
engines emit one string per crop. Both have to land in the same
``list[list[str]]`` so the comparison view can diff them.

The invariant every caller relies on: **the returned matrix is rectangular**.
Ragged rows are padded with empty strings to the widest row. That is what makes
"blank areas" survive — a row that is missing its trailing cells still occupies
the right number of columns.
"""

from __future__ import annotations

import csv
import html
import io
import re

# A Markdown table separator row: | --- | :---: | ---: |
_MD_SEPARATOR = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_MD_PIPE = re.compile(r"(?<!\\)\|")
_HTML_TABLE = re.compile(r"<table\b[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
_HTML_ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_HTML_CELL = re.compile(r"<t[dh]\b([^>]*)>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_HTML_TAG = re.compile(r"<[^>]+>")
_COLSPAN = re.compile(r"colspan\s*=\s*[\"']?(\d+)", re.IGNORECASE)
_ROWSPAN = re.compile(r"rowspan\s*=\s*[\"']?(\d+)", re.IGNORECASE)


def _clean(text: str) -> str:
    """Collapse whitespace and unescape entities. Cell text is single-line."""
    text = html.unescape(text)
    text = text.replace("\u00a0", " ")
    return " ".join(text.split())


def pad(matrix: list[list[str]]) -> list[list[str]]:
    """Pad every row to the width of the widest row."""
    if not matrix:
        return []
    width = max(len(row) for row in matrix)
    return [row + [""] * (width - len(row)) for row in matrix]


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def from_markdown(text: str) -> list[list[str]]:
    """Extract the first Markdown pipe table in `text`.

    Separator rows are dropped. Escaped pipes (``\\|``) are preserved as literal
    pipes rather than treated as delimiters.
    """
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            # A table may be preceded by prose; stop once we have rows and hit
            # something that is clearly not part of the table.
            if rows:
                break
            continue
        if _MD_SEPARATOR.match(stripped) and "-" in stripped:
            continue
        cells = _MD_PIPE.split(stripped)
        # Leading and trailing empty fields come from the outer pipes.
        if cells and cells[0].strip() == "":
            cells = cells[1:]
        if cells and cells[-1].strip() == "":
            cells = cells[:-1]
        rows.append([_clean(cell.replace("\\|", "|")) for cell in cells])
    return pad(rows)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


def from_html(text: str) -> list[list[str]]:
    """Extract the first HTML table, honouring colspan and rowspan.

    Spans matter for BOM tables: a merged header cell must not shift every
    subsequent column left, or the whole grid misaligns.
    """
    match = _HTML_TABLE.search(text)
    if not match:
        return []

    grid: list[list[str]] = []
    occupied: dict[tuple[int, int], str] = {}

    for row_index, row_html in enumerate(_HTML_ROW.findall(match.group(1))):
        row: list[str] = []
        col_index = 0
        for attrs, cell_html in _HTML_CELL.findall(row_html):
            # Skip positions already claimed by a rowspan from above.
            while (row_index, col_index) in occupied:
                row.append(occupied.pop((row_index, col_index)))
                col_index += 1

            value = _clean(_HTML_TAG.sub(" ", cell_html))
            colspan = int(m.group(1)) if (m := _COLSPAN.search(attrs)) else 1
            rowspan = int(m.group(1)) if (m := _ROWSPAN.search(attrs)) else 1

            for offset in range(colspan):
                row.append(value)
                for down in range(1, rowspan):
                    occupied[(row_index + down, col_index + offset)] = value
            col_index += colspan

        # Trailing cells claimed by a rowspan that started in an earlier row.
        while (row_index, col_index) in occupied:
            row.append(occupied.pop((row_index, col_index)))
            col_index += 1

        grid.append(row)

    return pad(grid)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def from_csv(text: str) -> list[list[str]]:
    """Parse CSV, tolerating a trailing newline and ragged rows."""
    reader = csv.reader(io.StringIO(text.strip()))
    return pad([[_clean(cell) for cell in row] for row in reader if row])


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def to_matrix(text: str | None) -> list[list[str]]:
    """Best-effort conversion of any engine output to a rectangular matrix.

    Tries HTML, then Markdown, then CSV. Returns ``[]`` when nothing tabular is
    present, which the caller treats as "this engine produced no table".
    """
    if not text or not text.strip():
        return []

    if "<table" in text.lower():
        matrix = from_html(text)
        if matrix:
            return matrix

    if "|" in text:
        matrix = from_markdown(text)
        if matrix:
            return matrix

    # CSV is the last resort: only accept it if it actually has structure.
    matrix = from_csv(text)
    if len(matrix) >= 1 and max((len(row) for row in matrix), default=0) >= 2:
        return matrix
    return []


def matrix_to_csv(matrix: list[list[str]]) -> str:
    """Render a matrix as CSV with a trailing newline."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows(matrix)
    return buffer.getvalue()


def matrix_to_markdown(matrix: list[list[str]]) -> str:
    """Render a matrix as a Markdown pipe table."""
    if not matrix:
        return ""
    width = max(len(row) for row in matrix)
    rows = [row + [""] * (width - len(row)) for row in matrix]

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |"

    header = line(rows[0])
    separator = "| " + " | ".join("---" for _ in range(width)) + " |"
    body = [line(row) for row in rows[1:]]
    return "\n".join([header, separator, *body])
