#!/usr/bin/env python3
"""Deterministic transcript quality evaluation for Persian sales calls.

The runner intentionally does not call a transcription provider. It compares a
versioned reference dataset with hypotheses produced by any provider, so results
remain reproducible and provider-neutral.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ARABIC_TO_PERSIAN = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ة": "ه",
        "ۀ": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "ٱ": "ا",
        "ء": "",
        "ـ": "",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
    }
)
DIACRITICS = re.compile(r"[\u064b-\u065f\u0670\u06d6-\u06ed]")
NON_WORD = re.compile(r"[^\w\s]", flags=re.UNICODE)
WHITESPACE = re.compile(r"\s+")
NUMBER = re.compile(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*(?!\w)")


def normalize_unicode(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).translate(ARABIC_TO_PERSIAN)
    text = DIACRITICS.sub("", text).replace("\u200c", " ").replace("\u200f", " ")
    return text


def normalize_text(value: str) -> str:
    text = normalize_unicode(value)
    text = NON_WORD.sub(" ", text.lower())
    return WHITESPACE.sub(" ", text).strip()


def tokenize(value: str) -> list[str]:
    normalized = normalize_text(value)
    return normalized.split() if normalized else []


def characters(value: str) -> list[str]:
    return list(normalize_text(value).replace(" ", ""))


def align(
    reference: Sequence[str], hypothesis: Sequence[str]
) -> tuple[int, list[dict[str, Any]]]:
    """Return Levenshtein distance and an auditable alignment."""
    rows, cols = len(reference) + 1, len(hypothesis) + 1
    costs = [[0] * cols for _ in range(rows)]
    moves = [[""] * cols for _ in range(rows)]
    for i in range(1, rows):
        costs[i][0], moves[i][0] = i, "deletion"
    for j in range(1, cols):
        costs[0][j], moves[0][j] = j, "insertion"

    for i in range(1, rows):
        for j in range(1, cols):
            if reference[i - 1] == hypothesis[j - 1]:
                costs[i][j] = costs[i - 1][j - 1]
                moves[i][j] = "equal"
                continue
            choices = (
                (costs[i - 1][j - 1] + 1, "substitution"),
                (costs[i - 1][j] + 1, "deletion"),
                (costs[i][j - 1] + 1, "insertion"),
            )
            costs[i][j], moves[i][j] = min(choices, key=lambda item: item[0])

    operations: list[dict[str, Any]] = []
    i, j = len(reference), len(hypothesis)
    while i or j:
        move = moves[i][j]
        if move in {"equal", "substitution"}:
            operations.append(
                {
                    "operation": move,
                    "reference": reference[i - 1],
                    "hypothesis": hypothesis[j - 1],
                }
            )
            i -= 1
            j -= 1
        elif move == "deletion":
            operations.append(
                {"operation": move, "reference": reference[i - 1], "hypothesis": None}
            )
            i -= 1
        elif move == "insertion":
            operations.append(
                {"operation": move, "reference": None, "hypothesis": hypothesis[j - 1]}
            )
            j -= 1
        else:  # defensive guard for malformed internal state
            raise RuntimeError(f"alignment failed at {i},{j}")
    operations.reverse()
    return costs[-1][-1], operations


def rate(errors: int, reference_units: int, hypothesis_units: int) -> float:
    if reference_units:
        return errors / reference_units
    return 0.0 if hypothesis_units == 0 else 1.0


def normalize_items(values: Iterable[Any]) -> Counter[str]:
    return Counter(value for item in values if (value := normalize_text(str(item))))


def multiset_score(expected: Iterable[Any], predicted: Iterable[Any]) -> dict[str, Any]:
    expected_counter = normalize_items(expected)
    predicted_counter = normalize_items(predicted)
    matched = sum((expected_counter & predicted_counter).values())
    expected_total, predicted_total = (
        sum(expected_counter.values()),
        sum(predicted_counter.values()),
    )
    precision = (
        matched / predicted_total
        if predicted_total
        else (1.0 if expected_total == 0 else 0.0)
    )
    recall = (
        matched / expected_total
        if expected_total
        else (1.0 if predicted_total == 0 else 0.0)
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "expected": expected_total,
        "predicted": predicted_total,
        "matched": matched,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "accuracy_definition": "exact normalized multiset recall",
        "accuracy": round(recall, 6),
    }


def flatten_entities(
    entities: dict[str, Any],
) -> tuple[list[str], dict[str, list[str]]]:
    flattened: list[str] = []
    by_type: dict[str, list[str]] = {}
    for kind, raw_values in sorted((entities or {}).items()):
        values = raw_values if isinstance(raw_values, list) else [raw_values]
        clean = [
            str(value) for value in values if value is not None and str(value).strip()
        ]
        by_type[str(kind)] = clean
        flattened.extend(f"{kind}:{value}" for value in clean)
    return flattened, by_type


def extract_numbers(text: str) -> list[str]:
    normalized = normalize_unicode(text).replace("٫", ".").replace("٬", ",")
    return [item.replace(",", "") for item in NUMBER.findall(normalized)]


def timestamp_score(
    reference: list[dict[str, Any]], hypothesis: list[dict[str, Any]], tolerance: float
) -> dict[str, Any] | None:
    if not reference and not hypothesis:
        return None
    expected_boundaries = len(reference) * 2
    matched = 0
    absolute_errors: list[float] = []
    for expected, predicted in zip(reference, hypothesis):
        for key in ("start", "end"):
            if expected.get(key) is None or predicted.get(key) is None:
                continue
            difference = abs(float(expected[key]) - float(predicted[key]))
            absolute_errors.append(difference)
            matched += int(difference <= tolerance)
    return {
        "tolerance_seconds": tolerance,
        "expected_boundaries": expected_boundaries,
        "matched_boundaries": matched,
        "accuracy": round(matched / expected_boundaries, 6)
        if expected_boundaries
        else None,
        "mean_absolute_error_seconds": round(
            sum(absolute_errors) / len(absolute_errors), 6
        )
        if absolute_errors
        else None,
        "alignment": "segments are compared by position; use stable segment ordering",
    }


def evaluate_sample(
    sample: dict[str, Any], dataset_dir: Path, tolerance: float
) -> dict[str, Any]:
    sample_id = str(sample.get("id", "")).strip()
    if not sample_id:
        raise ValueError("every sample requires a non-empty id")
    reference_text = str(sample.get("reference_text", ""))
    hypothesis_text = str(sample.get("hypothesis_text", ""))
    reference_words, hypothesis_words = (
        tokenize(reference_text),
        tokenize(hypothesis_text),
    )
    word_errors, word_alignment = align(reference_words, hypothesis_words)
    reference_chars, hypothesis_chars = (
        characters(reference_text),
        characters(hypothesis_text),
    )
    char_errors, _ = align(reference_chars, hypothesis_chars)

    operation_counts = Counter(item["operation"] for item in word_alignment)
    reference_entities, reference_by_type = flatten_entities(
        sample.get("reference_entities", {})
    )
    predicted_entities, predicted_by_type = flatten_entities(
        sample.get("predicted_entities", {})
    )
    entity_types = sorted(set(reference_by_type) | set(predicted_by_type))
    entity_by_type = {
        kind: multiset_score(
            reference_by_type.get(kind, []), predicted_by_type.get(kind, [])
        )
        for kind in entity_types
    }
    reference_numbers = sample.get("reference_numbers")
    predicted_numbers = sample.get("predicted_numbers")
    reference_numbers = (
        reference_numbers
        if reference_numbers is not None
        else extract_numbers(reference_text)
    )
    predicted_numbers = (
        predicted_numbers
        if predicted_numbers is not None
        else extract_numbers(hypothesis_text)
    )

    audio_path = sample.get("audio_path")
    resolved_audio = (dataset_dir / str(audio_path)).resolve() if audio_path else None
    return {
        "id": sample_id,
        "audio_path": str(audio_path) if audio_path else None,
        "audio_exists": resolved_audio.is_file() if resolved_audio else None,
        "reference_words": len(reference_words),
        "hypothesis_words": len(hypothesis_words),
        "word_errors": word_errors,
        "wer": round(rate(word_errors, len(reference_words), len(hypothesis_words)), 6),
        "reference_characters": len(reference_chars),
        "hypothesis_characters": len(hypothesis_chars),
        "character_errors": char_errors,
        "cer": round(rate(char_errors, len(reference_chars), len(hypothesis_chars)), 6),
        "operations": {
            "substitutions": operation_counts["substitution"],
            "deletions": operation_counts["deletion"],
            "insertions": operation_counts["insertion"],
        },
        "error_examples": [
            item for item in word_alignment if item["operation"] != "equal"
        ][:20],
        "entity": {
            "overall": multiset_score(reference_entities, predicted_entities),
            "by_type": entity_by_type,
        },
        "number": multiset_score(reference_numbers, predicted_numbers),
        "timestamp": timestamp_score(
            sample.get("reference_segments", []),
            sample.get("predicted_segments", []),
            tolerance,
        ),
    }


def sum_scores(samples: list[dict[str, Any]], key: str) -> dict[str, Any]:
    expected = sum(item[key]["expected"] for item in samples)
    predicted = sum(item[key]["predicted"] for item in samples)
    matched = sum(item[key]["matched"] for item in samples)
    return multiset_score(
        ["x"] * expected, ["x"] * matched + ["y"] * (predicted - matched)
    )


def evaluate_dataset(
    dataset: dict[str, Any], dataset_path: Path, tolerance: float
) -> dict[str, Any]:
    raw_samples = dataset.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        raise ValueError("dataset.samples must be a non-empty list")
    identifiers = [str(item.get("id", "")) for item in raw_samples]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("sample ids must be unique")
    samples = [
        evaluate_sample(item, dataset_path.parent, tolerance) for item in raw_samples
    ]
    total_reference_words = sum(item["reference_words"] for item in samples)
    total_hypothesis_words = sum(item["hypothesis_words"] for item in samples)
    total_word_errors = sum(item["word_errors"] for item in samples)
    total_reference_chars = sum(item["reference_characters"] for item in samples)
    total_hypothesis_chars = sum(item["hypothesis_characters"] for item in samples)
    total_char_errors = sum(item["character_errors"] for item in samples)
    timestamp_results = [
        item["timestamp"] for item in samples if item["timestamp"] is not None
    ]
    timestamp_expected = sum(item["expected_boundaries"] for item in timestamp_results)
    timestamp_matched = sum(item["matched_boundaries"] for item in timestamp_results)
    entity_wrapped = [{"value": item["entity"]["overall"]} for item in samples]
    number_wrapped = [{"value": item["number"]} for item in samples]
    contains_real_calls = bool(dataset.get("contains_real_calls", False))
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "name": str(dataset.get("name", dataset_path.stem)),
            "version": str(dataset.get("version", "unversioned")),
            "path": dataset_path.name,
            "contains_real_calls": contains_real_calls,
            "sample_count": len(samples),
        },
        "quality_claim": {
            "measured": contains_real_calls,
            "status": "measured_on_real_calls"
            if contains_real_calls
            else "NOT_MEASURED_ON_REAL_CALLS",
            "note": (
                "These figures may be used for the declared real-call dataset only."
                if contains_real_calls
                else "Synthetic examples validate the evaluator, not production transcription accuracy."
            ),
        },
        "aggregate": {
            "reference_words": total_reference_words,
            "word_errors": total_word_errors,
            "wer": round(
                rate(total_word_errors, total_reference_words, total_hypothesis_words),
                6,
            ),
            "reference_characters": total_reference_chars,
            "character_errors": total_char_errors,
            "cer": round(
                rate(total_char_errors, total_reference_chars, total_hypothesis_chars),
                6,
            ),
            "entity": sum_scores(entity_wrapped, "value"),
            "number": sum_scores(number_wrapped, "value"),
            "timestamp_accuracy": round(timestamp_matched / timestamp_expected, 6)
            if timestamp_expected
            else None,
        },
        "samples": samples,
    }


def render_html(report: dict[str, Any]) -> str:
    aggregate = report["aggregate"]
    rows = []
    for sample in report["samples"]:
        timestamp_cell = (
            "—"
            if sample["timestamp"] is None
            else f"{sample['timestamp']['accuracy']:.2%}"
        )
        rows.append(
            "<tr>"
            f"<td>{html.escape(sample['id'])}</td>"
            f"<td>{sample['wer']:.2%}</td><td>{sample['cer']:.2%}</td>"
            f"<td>{sample['entity']['overall']['accuracy']:.2%}</td>"
            f"<td>{sample['number']['accuracy']:.2%}</td>"
            f"<td>{timestamp_cell}</td>"
            "</tr>"
        )
    status = html.escape(report["quality_claim"]["status"])
    note = html.escape(report["quality_claim"]["note"])
    return f"""<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>گزارش ارزیابی رونویسی</title>
<style>body{{font-family:Tahoma,Arial,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#15253d}}.warning{{background:#fff5d6;border-right:5px solid #d68b00;padding:1rem}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem;margin:1.5rem 0}}.card{{border:1px solid #dce3eb;border-radius:12px;padding:1rem}}.value{{font-size:1.6rem;font-weight:700}}table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #dce3eb;padding:.7rem;text-align:right}}code{{direction:ltr;unicode-bidi:embed}}</style></head>
<body><h1>گزارش ارزیابی کیفیت رونویسی</h1><p class="warning"><strong>{status}</strong><br>{note}</p>
<p>مجموعه: {html.escape(report["dataset"]["name"])} — نسخه {html.escape(report["dataset"]["version"])} — {report["dataset"]["sample_count"]} نمونه</p>
<section class="cards"><div class="card">WER<div class="value">{aggregate["wer"]:.2%}</div></div><div class="card">CER<div class="value">{aggregate["cer"]:.2%}</div></div><div class="card">دقت موجودیت<div class="value">{aggregate["entity"]["accuracy"]:.2%}</div></div><div class="card">دقت عدد<div class="value">{aggregate["number"]["accuracy"]:.2%}</div></div></section>
<table><thead><tr><th>نمونه</th><th>WER</th><th>CER</th><th>موجودیت</th><th>عدد</th><th>زمان</th></tr></thead><tbody>{"".join(rows)}</tbody></table>
<p>تعریف «دقت موجودیت/عدد» در JSON گزارش ثبت شده است. این گزارش به‌تنهایی ادعای دقت عملیاتی ایجاد نمی‌کند.</p></body></html>"""


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=root / "references" / "sample_dataset.json"
    )
    parser.add_argument(
        "--json-output", type=Path, default=root / "results" / "latest_report.json"
    )
    parser.add_argument(
        "--html-output", type=Path, default=root / "results" / "latest_report.html"
    )
    parser.add_argument("--timestamp-tolerance", type=float, default=0.75)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        dataset_path = args.dataset.resolve()
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        report = evaluate_dataset(dataset, dataset_path, args.timestamp_tolerance)
        atomic_write(
            args.json_output.resolve(),
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )
        atomic_write(args.html_output.resolve(), render_html(report))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"evaluation failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"evaluated {report['dataset']['sample_count']} samples: "
        f"WER={report['aggregate']['wer']:.2%}, CER={report['aggregate']['cer']:.2%}, "
        f"claim={report['quality_claim']['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
