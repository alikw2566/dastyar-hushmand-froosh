from collections import defaultdict
from typing import Any


def field(item: Any, name: str, default=None):
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def normalize_segments(raw_segments: list[Any]) -> list[dict]:
    normalized = []
    for position, item in enumerate(raw_segments):
        text = str(field(item, "text", "")).strip()
        if not text:
            continue
        start = field(item, "start")
        end = field(item, "end")
        normalized.append({
            "position": position,
            "speaker": str(field(item, "speaker", "unknown")),
            "text": text,
            "start": float(start) if start is not None else None,
            "end": float(end) if end is not None else None,
        })
    return normalized


def calculate_metrics(segments: list[dict]) -> dict:
    talk_seconds = defaultdict(float)
    turns = defaultdict(int)
    longest = defaultdict(float)
    explicit_questions = defaultdict(int)
    timed: list[tuple[float, float]] = []

    for segment in segments:
        speaker = segment["speaker"]
        turns[speaker] += 1
        explicit_questions[speaker] += segment["text"].count("?") + segment["text"].count("؟")
        start, end = segment["start"], segment["end"]
        if start is not None and end is not None and end >= start:
            duration = end - start
            talk_seconds[speaker] += duration
            longest[speaker] = max(longest[speaker], duration)
            timed.append((start, end))

    timed.sort()
    total_talk = sum(talk_seconds.values())
    silence = overlap = 0.0
    previous_end = timed[0][1] if timed else 0.0
    for start, end in timed[1:]:
        if start > previous_end:
            silence += start - previous_end
        elif start < previous_end:
            overlap += min(previous_end, end) - start
        previous_end = max(previous_end, end)

    return {
        "call_span_seconds": round(max((end for _, end in timed), default=0), 1) if timed else None,
        "detected_speech_seconds": round(total_talk, 1) if timed else None,
        "detected_silence_seconds": round(silence, 1) if timed else None,
        "detected_overlap_seconds": round(overlap, 1) if timed else None,
        "speakers": {
            speaker: {
                "turn_count": turns[speaker],
                "talk_seconds": round(talk_seconds[speaker], 1) if talk_seconds[speaker] else None,
                "talk_share_percent": round(talk_seconds[speaker] / total_talk * 100, 1) if total_talk else None,
                "longest_turn_seconds": round(longest[speaker], 1) if longest[speaker] else None,
                "explicit_question_marks": explicit_questions[speaker],
            }
            for speaker in turns
        },
    }


def transcript_text(segments: list[dict]) -> str:
    lines = []
    for segment in segments:
        timestamp = f"[{segment['start']:.1f}s] " if segment["start"] is not None else ""
        lines.append(f"{timestamp}{segment['speaker']}: {segment['text']}")
    return "\n".join(lines)
