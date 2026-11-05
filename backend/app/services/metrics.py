"""Accuracy and hallucination metrics.

Two questions matter for engineering drawings:

1. Did the engine read the text correctly?  -> CER / WER against a reference.
2. Did the engine invent text that is not on the page?  -> hallucination probes.

The second matters more than usual here. General-purpose VLMs are happy to
produce fluent, plausible-looking prose about a schematic that contains no
prose at all. A drawing has almost no sentences, so a high "prose ratio" is a
strong hallucination signal.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any

import jiwer

# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_WHITESPACE = re.compile(r"\s+")
# Keep characters that carry meaning on a drawing: digits, letters, and the
# symbols used in dimension callouts.
_KEEP = re.compile(r"[^0-9A-Za-z\u00C0-\u024F\u0370-\u03FF\u0400-\u04FF"
                   r"ØøØ°±µΩΦΔ∅⌀\"'.,:;/\-+()\[\]<>#%&*=_|~^ ]")


def normalise(text: str) -> str:
    """Collapse whitespace and drop markup noise before comparison."""
    if not text:
        return ""
    # Strip common Markdown/HTML scaffolding so a Markdown engine is not
    # penalised for formatting that a plain-text engine never emits.
    text = re.sub(r"<[^>]{1,80}>", " ", text)
    text = re.sub(r"[#*_`>]{1,}", " ", text)
    text = _KEEP.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def tokens(text: str) -> list[str]:
    return normalise(text).split()


# ---------------------------------------------------------------------------
# CER / WER
# ---------------------------------------------------------------------------


@dataclass
class Accuracy:
    cer: float
    wer: float
    reference: str
    reference_chars: int


def score_against(reference: str, hypothesis: str, *, reference_name: str) -> Accuracy:
    ref = normalise(reference)
    hyp = normalise(hypothesis)

    if not ref:
        return Accuracy(cer=0.0, wer=0.0, reference=reference_name, reference_chars=0)

    if not hyp:
        return Accuracy(cer=1.0, wer=1.0, reference=reference_name, reference_chars=len(ref))

    cer = float(jiwer.cer(ref, hyp))
    wer = float(jiwer.wer(ref, hyp))
    return Accuracy(
        cer=min(cer, 1.0),
        wer=min(wer, 1.0),
        reference=reference_name,
        reference_chars=len(ref),
    )


def consensus_reference(texts: dict[str, str]) -> tuple[str, str]:
    """Pick the engine whose output is closest to all the others.

    For raster pages there is no ground truth, so we use the medoid of the
    candidate outputs: the engine with the lowest median pairwise CER. It is
    circular by construction, but it reliably identifies the outlier engines
    (the ones that hallucinate or return almost nothing).
    """
    candidates = {name: normalise(text) for name, text in texts.items() if normalise(text)}
    if not candidates:
        return "", "none"
    if len(candidates) == 1:
        name = next(iter(candidates))
        return candidates[name], name

    names = list(candidates)
    best_name = names[0]
    best_score = float("inf")

    for name in names:
        distances = []
        for other in names:
            if other == name:
                continue
            try:
                distances.append(float(jiwer.cer(candidates[other], candidates[name])))
            except ValueError:
                distances.append(1.0)
        median = statistics.median(distances) if distances else 1.0
        if median < best_score:
            best_score = median
            best_name = name

    return candidates[best_name], best_name


# ---------------------------------------------------------------------------
# Hallucination probes
# ---------------------------------------------------------------------------

# A "prose line" is a long run of words with no digits. Drawings are made of
# short labels and dimension callouts, so prose is a red flag.
_PROSE_MIN_WORDS = 12


@dataclass
class Hallucination:
    repetition_ratio: float
    novel_token_rate: float
    prose_ratio: float
    length_zscore: float
    garbage_ratio: float
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repetition_ratio": round(self.repetition_ratio, 4),
            "novel_token_rate": round(self.novel_token_rate, 4),
            "prose_ratio": round(self.prose_ratio, 4),
            "length_zscore": round(self.length_zscore, 3),
            "garbage_ratio": round(self.garbage_ratio, 4),
            "flags": self.flags,
        }


def _repetition_ratio(text: str) -> float:
    """Fraction of 5-gram tokens that repeat an earlier 5-gram."""
    words = tokens(text)
    if len(words) < 10:
        return 0.0
    grams = [tuple(words[i : i + 5]) for i in range(len(words) - 4)]
    if not grams:
        return 0.0
    return 1.0 - (len(set(grams)) / len(grams))


def _prose_ratio(text: str) -> float:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return 0.0
    prose = 0
    for line in lines:
        words = line.split()
        if len(words) >= _PROSE_MIN_WORDS and not any(ch.isdigit() for ch in line):
            prose += 1
    return prose / len(lines)


def _garbage_ratio(text: str) -> float:
    """Share of characters outside printable ASCII/Latin-1 plus common symbols."""
    if not text:
        return 0.0
    bad = 0
    for ch in text:
        code = ord(ch)
        if ch in "\n\r\t":
            continue
        if 32 <= code <= 126 or 160 <= code <= 0x24F:
            continue
        if ch in "Øø°±µΩΦΔ∅⌀–—‘’“”…":
            continue
        bad += 1
    return bad / len(text)


def detect_hallucination(
    text: str,
    *,
    peer_lengths: list[int],
    peer_vocabulary: set[str] | None = None,
) -> Hallucination:
    words = tokens(text)
    length = len(words)

    # Robust z-score via median absolute deviation: one engine returning 10x
    # the text of everyone else is the classic VLM failure mode.
    zscore = 0.0
    if len(peer_lengths) >= 3:
        median = statistics.median(peer_lengths)
        deviations = [abs(value - median) for value in peer_lengths]
        mad = statistics.median(deviations) or 1.0
        zscore = (length - median) / (1.4826 * mad)

    novel_rate = 0.0
    if peer_vocabulary and words:
        novel = sum(1 for word in words if word.lower() not in peer_vocabulary)
        novel_rate = novel / len(words)

    repetition = _repetition_ratio(text)
    prose = _prose_ratio(text)
    garbage = _garbage_ratio(text)

    flags: list[str] = []
    if repetition > 0.30:
        flags.append("repetitive")
    if prose > 0.25:
        flags.append("prose-on-drawing")
    if abs(zscore) > 3.5:
        flags.append("length-outlier")
    if garbage > 0.05:
        flags.append("encoding-garbage")
    if novel_rate > 0.60:
        flags.append("novel-vocabulary")

    return Hallucination(
        repetition_ratio=repetition,
        novel_token_rate=novel_rate,
        prose_ratio=prose,
        length_zscore=zscore,
        garbage_ratio=garbage,
        flags=flags,
    )


# ---------------------------------------------------------------------------
# Engineering-drawing specific signals
# ---------------------------------------------------------------------------

# Dimension callouts: diameter, radius, plus/minus, and unit suffixes.
_DIMENSION_PATTERNS = {
    "diameter": re.compile(r"(?:Ø|⌀|∅|\bDIA\b|\bDIA\.)\s*\d"),
    "radius": re.compile(r"\bR\s*\d+(?:\.\d+)?"),
    "plus_minus": re.compile(r"±\s*\d"),
    "mm": re.compile(r"\d+(?:\.\d+)?\s*mm\b", re.IGNORECASE),
    "inch": re.compile(r"\d+(?:\.\d+)?\s*(?:\"|in\b|inch\b)", re.IGNORECASE),
    "angle": re.compile(r"\d+(?:\.\d+)?\s*°"),
    "nps": re.compile(r"\bNPS\s*\d", re.IGNORECASE),
    "schedule": re.compile(r"\bSCH(?:ED)?\.?\s*\d+", re.IGNORECASE),
    "weld": re.compile(r"(?:fillet|groove|butt|tack)\s*weld", re.IGNORECASE),
    "revision": re.compile(r"\bREV(?:ISION)?\.?\s*[A-Z0-9]\b", re.IGNORECASE),
    "part_number": re.compile(r"\b(?:P/?N|PART\s*(?:NO|NUMBER|#))\b", re.IGNORECASE),
    "material": re.compile(r"\b(?:A36|A992|A500|304|316L?|6061|7075)\b"),
}


def dimension_signals(text: str) -> dict[str, int]:
    """Count engineering-drawing constructs an engine managed to read."""
    return {
        name: len(pattern.findall(text))
        for name, pattern in _DIMENSION_PATTERNS.items()
    }


def dimension_delta(
    candidate: dict[str, int], reference: dict[str, int]
) -> dict[str, Any]:
    """How many callouts the engine missed or invented, per category."""
    missed = 0
    invented = 0
    detail: dict[str, dict[str, int]] = {}
    for key, ref_count in reference.items():
        got = candidate.get(key, 0)
        if got < ref_count:
            missed += ref_count - got
        elif got > ref_count:
            invented += got - ref_count
        if got != ref_count:
            detail[key] = {"reference": ref_count, "candidate": got}
    return {"missed": missed, "invented": invented, "detail": detail}


# ---------------------------------------------------------------------------
# Table structure
# ---------------------------------------------------------------------------

_TABLE_ROW = re.compile(r"<tr[^>]*>", re.IGNORECASE)
_TABLE_CELL = re.compile(r"<t[dh][^>]*>", re.IGNORECASE)
_MD_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


def table_shape(text: str) -> dict[str, int]:
    """Approximate table structure from HTML or Markdown tables."""
    html_rows = len(_TABLE_ROW.findall(text))
    html_cells = len(_TABLE_CELL.findall(text))
    md_rows = len(_MD_TABLE_ROW.findall(text))
    return {
        "rows": html_rows or md_rows,
        "cells": html_cells or (md_rows * max(1, text.count("|") // max(md_rows, 1))),
    }


def table_match(candidate: dict[str, int], reference: dict[str, int]) -> dict[str, Any]:
    ref_rows = reference.get("rows", 0)
    if ref_rows == 0:
        return {"applicable": False, "row_delta": 0, "cell_delta": 0}
    return {
        "applicable": True,
        "row_delta": candidate.get("rows", 0) - ref_rows,
        "cell_delta": candidate.get("cells", 0) - reference.get("cells", 0),
    }


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


def evaluate(
    outputs: dict[str, str],
    *,
    reference_text: str | None,
    reference_name: str,
) -> dict[str, dict[str, Any]]:
    """Score every engine output against a reference and against its peers.

    ``outputs`` maps engine_id -> extracted text.
    """
    if reference_text is None:
        reference_text, reference_name = consensus_reference(outputs)

    lengths = {name: len(tokens(text)) for name, text in outputs.items()}
    vocabulary: set[str] = set()
    for text in outputs.values():
        vocabulary.update(word.lower() for word in tokens(text))

    ref_dimensions = dimension_signals(reference_text)
    ref_tables = table_shape(reference_text)

    report: dict[str, dict[str, Any]] = {}
    for engine_id, text in outputs.items():
        accuracy = score_against(reference_text, text, reference_name=reference_name)
        peers = [value for name, value in lengths.items() if name != engine_id]
        hallucination = detect_hallucination(
            text, peer_lengths=peers, peer_vocabulary=vocabulary
        )
        hallucination_dict = hallucination.to_dict()
        # Word count lives with the hallucination block so the CSV export and
        # the UI can read it from one place.
        hallucination_dict["word_count"] = lengths[engine_id]
        report[engine_id] = {
            "cer": round(accuracy.cer, 4),
            "wer": round(accuracy.wer, 4),
            "reference": accuracy.reference,
            "reference_chars": accuracy.reference_chars,
            "hallucination": hallucination_dict,
            "dimensions": dimension_delta(dimension_signals(text), ref_dimensions),
            "tables": table_match(table_shape(text), ref_tables),
            "word_count": lengths[engine_id],
        }
    return report
