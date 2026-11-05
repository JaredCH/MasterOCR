"""Tests for the registry, contract, metrics, and runner isolation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engines import registry
from app.services import metrics


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_ids_are_unique():
    ids = [engine.id for engine in registry.ENGINES]
    assert len(ids) == len(set(ids))


def test_registry_has_all_tiers():
    counts = registry.tier_counts()
    assert set(counts) == {1, 2, 3, 4, 5}
    assert counts[1] >= 15


def test_gpu_engines_are_never_runnable():
    for engine in registry.ENGINES:
        if engine.requires_gpu:
            assert not engine.runnable_on_railway
            assert not engine.enabled_by_default


def test_every_engine_declares_a_license():
    for engine in registry.ENGINES:
        assert engine.license, f"{engine.id} has no license"
        assert engine.license_note, f"{engine.id} has no license note"


def test_api_engines_declare_a_credential():
    for engine in registry.ENGINES:
        if engine.tier in (3, 4):
            assert engine.requires_key, f"{engine.id} is an API engine with no key"


def test_get_engine_raises_on_unknown_id():
    with pytest.raises(KeyError):
        registry.get_engine("does-not-exist")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_normalise_strips_markdown_and_collapses_space():
    assert metrics.normalise("##  Hello\n\n**world**") == "Hello world"


def test_identical_text_scores_zero_cer():
    text = "6\" 120 (.562) PIPE A333-GR6 SMLS"
    result = metrics.score_against(text, text, reference_name="test")
    assert result.cer == 0.0
    assert result.wer == 0.0


def test_empty_hypothesis_scores_one():
    result = metrics.score_against("some text", "", reference_name="test")
    assert result.cer == 1.0


def test_consensus_picks_the_medoid():
    outputs = {
        "good-a": "PIPE 6 INCH A333 GR6 SMLS 120",
        "good-b": "PIPE 6 INCH A333 GR6 SMLS 120",
        "outlier": "completely unrelated hallucinated prose about nothing",
    }
    reference, name = metrics.consensus_reference(outputs)
    assert name in {"good-a", "good-b"}
    assert "PIPE" in reference


def test_prose_ratio_flags_vlm_hallucination():
    drawing = "Ø2.5\nR1.0\n6\" PIPE\nA36 PLATE"
    hallucinated = (
        "This image shows a technical drawing of a piping spool that appears to "
        "be part of an industrial facility with various components visible."
    )
    assert metrics.detect_hallucination(drawing, peer_lengths=[4, 5, 6]).prose_ratio == 0.0
    assert metrics.detect_hallucination(hallucinated, peer_lengths=[4, 5, 6]).prose_ratio > 0


def test_repetition_detection():
    repeated = " ".join(["PIPE A333 GR6 SMLS"] * 40)
    result = metrics.detect_hallucination(repeated, peer_lengths=[10, 12, 14])
    assert result.repetition_ratio > 0.3
    assert "repetitive" in result.flags


def test_length_outlier_detection():
    result = metrics.detect_hallucination(
        " ".join(["word"] * 500), peer_lengths=[10, 11, 12, 13]
    )
    assert abs(result.length_zscore) > 3.5
    assert "length-outlier" in result.flags


def test_dimension_signals_reads_callouts():
    text = 'Ø2.5 R1.0 ±0.05 6" 120 mm NPS 4 SCH 40 REV B'
    signals = metrics.dimension_signals(text)
    assert signals["diameter"] == 1
    assert signals["radius"] == 1
    assert signals["plus_minus"] == 1
    assert signals["mm"] == 1
    assert signals["nps"] == 1
    assert signals["schedule"] == 1
    assert signals["revision"] == 1


def test_dimension_delta_counts_missed_callouts():
    reference = {"diameter": 3, "radius": 2, "mm": 5}
    candidate = {"diameter": 1, "radius": 2, "mm": 5}
    delta = metrics.dimension_delta(candidate, reference)
    assert delta["missed"] == 2
    assert delta["invented"] == 0


def test_table_shape_reads_html():
    html = "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>"
    shape = metrics.table_shape(html)
    assert shape["rows"] == 2
    assert shape["cells"] == 4


def test_evaluate_produces_a_row_per_engine():
    outputs = {
        "a": "PIPE 6 INCH A333 GR6",
        "b": "PIPE 6 INCH A333 GR6",
        "c": "",
    }
    report = metrics.evaluate(outputs, reference_text=None, reference_name="consensus")
    assert set(report) == {"a", "b", "c"}
    assert report["c"]["cer"] == 1.0
    assert report["a"]["cer"] == 0.0


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_contract_round_trip():
    from app.engines.contract import EngineResponse, PageResult

    response = EngineResponse(
        ok=True,
        engine_id="test",
        pages=[PageResult(page=1, text="hello", confidence=0.9)],
        meta={"version": "1"},
    )
    payload = json.loads(response.to_json())
    assert payload["ok"] is True
    assert payload["pages"][0]["text"] == "hello"
    assert payload["pages"][0]["confidence"] == 0.9


def test_page_result_best_text_prefers_markdown():
    from app.engines.contract import PageResult

    page = PageResult(page=1, text="plain", markdown="# rich")
    assert page.best_text() == "# rich"


# ---------------------------------------------------------------------------
# Runner isolation
# ---------------------------------------------------------------------------


def test_unavailable_engine_reports_reason_without_running():
    import asyncio

    from app.config import get_settings
    from app.engines.runner import run_engine

    settings = get_settings()
    gpu_engine = registry.get_engine("olmocr-local")
    outcome = asyncio.run(
        run_engine(
            gpu_engine,
            pdf_path=Path("nonexistent.pdf"),
            page_images=[],
            page_count=1,
            settings=settings,
        )
    )
    assert outcome.ok is False
    assert "GPU" in (outcome.error or "")


def test_missing_credential_reports_reason():
    from app.config import get_settings
    from app.engines.runner import is_available

    settings = get_settings()
    engine = registry.get_engine("mistral-ocr")
    available, reason = is_available(engine, settings)
    if not settings.mistral_key:
        assert available is False
        assert "credential" in reason.lower()
