"""Tests for the phase-2 region services: grid, tableparse, regions, store."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import grid, regions, tableparse  # noqa: E402
from app.services.store import Store  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ruled_table(width=300, height=200, cols=(0, 100, 200, 299),
                rows=(0, 66, 133, 199), line_width=2):
    """A synthetic ruled table image."""
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    for x in cols:
        draw.line([(x, 0), (x, height - 1)], fill=0, width=line_width)
    for y in rows:
        draw.line([(0, y), (width - 1, y)], fill=0, width=line_width)
    return image


# ---------------------------------------------------------------------------
# Grid detection
# ---------------------------------------------------------------------------


class TestGrid:
    def test_full_bleed_ruled_table(self):
        image = ruled_table()
        result = grid.detect_grid(image)
        assert (result.rows, result.cols) == (3, 3)
        assert result.method == "rows:lines,cols:lines"
        assert result.confidence >= 0.9

    def test_inset_ruled_table_has_no_phantom_columns(self):
        # Table drawn inset within a larger crop: the margin bands are empty,
        # so the outermost rules are the borders and no phantom cells appear.
        image = Image.new("L", (400, 300), 255)
        draw = ImageDraw.Draw(image)
        for x in (50, 150, 250, 350):
            draw.line([(x, 50), (x, 250)], fill=0, width=2)
        for y in (50, 116, 183, 250):
            draw.line([(50, y), (350, y)], fill=0, width=2)
        result = grid.detect_grid(image)
        assert (result.rows, result.cols) == (3, 3)

    def test_borderless_table_uses_whitespace(self):
        image = Image.new("L", (300, 100), 255)
        draw = ImageDraw.Draw(image)
        draw.rectangle((30, 20, 80, 50), fill=0)
        draw.rectangle((130, 20, 180, 50), fill=0)
        draw.rectangle((230, 20, 280, 50), fill=0)
        result = grid.detect_grid(image)
        assert result.cols == 3
        assert "whitespace" in result.method

    def test_manual_edges_win(self):
        image = ruled_table()
        result = grid.detect_grid(
            image, manual_cols=[0, 150, 300], manual_rows=[0, 100, 200]
        )
        assert result.method == "rows:manual,cols:manual"
        assert result.confidence == 1.0
        assert (result.rows, result.cols) == (2, 2)

    def test_degenerate_region(self):
        image = Image.new("L", (4, 4), 255)
        result = grid.detect_grid(image)
        assert result.method == "degenerate"
        assert result.warnings

    def test_cells_from_edges_covers_every_cell(self):
        cells = grid.cells_from_edges([0, 10, 20], [0, 10, 20, 30])
        assert len(cells) == 6  # 2 rows x 3 cols
        assert cells[0] == (0, 0, (0, 0, 10, 10))
        assert cells[-1] == (1, 2, (20, 10, 30, 20))


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------


class TestTableParse:
    def test_markdown_preserves_blank_cells(self):
        text = "| a | b | c |\n| --- | --- | --- |\n| 1 |  | 3 |"
        matrix = tableparse.from_markdown(text)
        assert matrix == [["a", "b", "c"], ["1", "", "3"]]

    def test_markdown_ragged_rows_are_padded(self):
        text = "| a | b | c |\n| --- | --- | --- |\n| 1 | 2 |"
        matrix = tableparse.from_markdown(text)
        assert all(len(row) == 3 for row in matrix)
        assert matrix[1] == ["1", "2", ""]

    def test_html_colspan_does_not_shift_columns(self):
        text = (
            '<table><tr><th colspan="2">HDR</th><th>Q</th></tr>'
            "<tr><td>a</td><td></td><td>3</td></tr></table>"
        )
        matrix = tableparse.from_html(text)
        assert matrix == [["HDR", "HDR", "Q"], ["a", "", "3"]]

    def test_csv_preserves_blanks(self):
        matrix = tableparse.from_csv("a,b,c\n1,,3\n")
        assert matrix == [["a", "b", "c"], ["1", "", "3"]]

    def test_dispatch(self):
        assert tableparse.to_matrix("| a | b |\n| --- | --- |\n| 1 | 2 |") == [
            ["a", "b"],
            ["1", "2"],
        ]
        assert tableparse.to_matrix("<table><tr><td>x</td></tr></table>") == [["x"]]
        assert tableparse.to_matrix("no table here") == []

    def test_matrix_to_markdown_roundtrip(self):
        matrix = [["a", ""], ["1", "2"]]
        rendered = tableparse.matrix_to_markdown(matrix)
        assert tableparse.from_markdown(rendered) == matrix

    def test_matrix_to_csv(self):
        assert tableparse.matrix_to_csv([["a", ""], ["1", "2"]]) == "a,\n1,2\n"


# ---------------------------------------------------------------------------
# Region geometry and cell classification
# ---------------------------------------------------------------------------


class TestRegions:
    def test_normalized_to_pixels(self):
        region = regions.Region(
            id="r", name="R", kind="table", x0=0.1, y0=0.1, x1=0.9, y1=0.9
        )
        assert regions.normalized_to_pixels(region, 1000, 2000) == (
            100, 200, 900, 1800,
        )

    def test_normalized_to_pixels_accepts_dicts(self):
        region = {"x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}
        assert regions.normalized_to_pixels(region, 100, 100) == (0, 0, 50, 50)

    def test_normalized_to_pixels_clamps(self):
        region = {"x0": -0.5, "y0": 0.0, "x1": 1.5, "y1": 2.0}
        assert regions.normalized_to_pixels(region, 100, 100) == (0, 0, 100, 100)

    def test_classify_cell_blank(self):
        assert regions.classify_cell("", None, 0.0) == "blank"
        assert regions.classify_cell(None, None, 0.0) == "blank"

    def test_classify_cell_ink_but_no_text_is_low(self):
        # Ink present but OCR returned nothing: a failed read, not a blank.
        assert regions.classify_cell("", None, 0.5) == "low"

    def test_classify_cell_low_confidence(self):
        assert regions.classify_cell("abc", 0.1, 0.5) == "low"
        assert regions.classify_cell("abc", 0.9, 0.5) == "ok"

    def test_cell_scaffold_preserves_blanks(self):
        image = ruled_table()
        result = grid.detect_grid(image)
        scaffold = regions.build_cell_matrix(image, result)
        assert len(scaffold) == 3 and len(scaffold[0]) == 3
        # Every cell exists up front, blank by default.
        assert all(cell["status"] == "blank" for row in scaffold for cell in row)

    def test_fill_cell(self):
        image = ruled_table()
        result = grid.detect_grid(image)
        scaffold = regions.build_cell_matrix(image, result)
        regions.fill_cell(scaffold[0][0], "pipe", 0.95)
        assert scaffold[0][0]["status"] == "ok"
        assert scaffold[0][0]["text"] == "pipe"
        regions.fill_cell(scaffold[0][1], "", None)
        assert scaffold[0][1]["status"] == "blank"

    def test_split_key_value_colon(self):
        assert regions.split_key_value("Work Order: 1256899") == (
            "Work Order", "1256899",
        )

    def test_split_key_value_wide_gap(self):
        assert regions.split_key_value("Piecemark   1555-BS01") == (
            "Piecemark", "1555-BS01",
        )

    def test_split_key_value_empty(self):
        assert regions.split_key_value("") == ("", "")

    def test_build_region_pdf(self, tmp_path):
        import pymupdf

        source = tmp_path / "src.pdf"
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), "hello region")
        doc.save(source)
        doc.close()

        output = tmp_path / "region.pdf"
        regions.build_region_pdf(source, 1, (36.0, 36.0, 300.0, 200.0), output)
        with pymupdf.open(output) as check:
            assert check.page_count == 1
            assert "hello" in check.load_page(0).get_text()


# ---------------------------------------------------------------------------
# Store CRUD
# ---------------------------------------------------------------------------


class TestStore:
    @pytest.fixture
    def store(self, tmp_path):
        return Store(tmp_path / "test.db")

    def test_layout_roundtrip(self, store):
        regions_data = [
            {"id": "r1", "name": "BOM", "kind": "table",
             "x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.5}
        ]
        store.save_layout(
            "doc1", 1, page_width_pt=612, page_height_pt=792,
            regions=regions_data,
        )
        layout = store.get_layout("doc1", 1)
        assert layout is not None
        assert layout["regions"][0]["name"] == "BOM"
        assert layout["page_width_pt"] == 612

    def test_layout_upsert(self, store):
        store.save_layout("doc1", 1, page_width_pt=612,
                          page_height_pt=792, regions=[{"id": "r1"}])
        store.save_layout("doc1", 1, page_width_pt=612,
                          page_height_pt=792, regions=[])
        assert store.get_layout("doc1", 1)["regions"] == []

    def test_missing_layout(self, store):
        assert store.get_layout("nope", 1) is None

    def test_region_run_and_results(self, store):
        run_id = store.create_region_run("doc1", 1)
        store.save_region_result(
            run_id, "r1", "rapidocr", status="ok", duration_ms=100,
            error=None,
            result={"rows": 2, "cols": 2, "cells": [["a", ""], ["", "d"]]},
        )
        store.finish_region_run(run_id, status="ok")

        run = store.get_region_run(run_id)
        assert run["status"] == "ok"

        results = store.get_region_results(run_id)
        assert results[0]["result"]["cells"][0][1] == ""

    def test_latest_results_prefers_finished_runs(self, store):
        first = store.create_region_run("doc1", 1)
        store.save_region_result(
            first, "r1", "e1", status="ok", duration_ms=1, error=None,
            result={"n": 1},
        )
        store.finish_region_run(first, status="ok")
        latest = store.get_latest_region_results("doc1", 1)
        assert latest and latest[0]["result"]["n"] == 1

        # A still-running run must not shadow the finished one.
        store.create_region_run("doc1", 1)
        assert store.get_latest_region_results("doc1", 1)[0]["result"]["n"] == 1

    def test_template_lifecycle(self, store):
        template_id = store.save_template(
            name="BOM", page_width_pt=612, page_height_pt=792,
            regions=[{"id": "r1", "name": "BOM"}],
        )
        assert store.get_template(template_id)["regions"][0]["name"] == "BOM"
        assert len(store.list_templates()) == 1
        assert store.delete_template(template_id)
        assert store.get_template(template_id) is None
