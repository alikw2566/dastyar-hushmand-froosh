"""Standalone speaker diarization for validated mono WAV audio files."""

from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import List, TypedDict  # noqa: UP035 - required public API signature

try:
    from pyannote.audio import Pipeline
except ImportError:  # pragma: no cover - exercised only in incomplete deployments
    Pipeline = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

MODEL_ID = "pyannote/speaker-diarization-3.1"


class DiarizationSegment(TypedDict):
    """A single anonymous speaker turn returned by the diarization model."""

    start: float
    end: float
    speaker: str


def _validate_mono_wav(audio_path: str) -> Path:
    path = Path(audio_path)
    if not path.is_file():
        raise FileNotFoundError(f"Audio file was not found: {path}")
    if path.suffix.lower() != ".wav":
        raise ValueError("Only WAV audio files are supported.")

    try:
        with wave.open(str(path), "rb") as wav_file:
            channels = wav_file.getnchannels()
    except (EOFError, OSError, wave.Error) as exc:
        raise ValueError("Audio file is not a valid WAV file.") from exc

    if channels != 1:
        raise ValueError(f"Expected a mono WAV file, but found {channels} channels.")
    return path


def diarize_audio(
    audio_path: str,
    hf_token: str,
) -> List[DiarizationSegment]:  # noqa: UP006 - required public API signature
    """Return anonymous speaker turns for a mono WAV file.

    This function performs speaker diarization only. It does not transcribe
    speech or assign business roles such as seller and customer.
    """

    token = hf_token.strip()
    if not token:
        raise ValueError("HuggingFace token is required.")

    path = _validate_mono_wav(audio_path)
    if Pipeline is None:
        raise RuntimeError("Pyannote speaker diarization is not installed.")

    try:
        pipeline = Pipeline.from_pretrained(MODEL_ID, use_auth_token=token)
    except Exception:  # noqa: BLE001 - normalize failures from third-party model loaders
        logger.error("Unable to load the Pyannote speaker diarization pipeline.")
        raise RuntimeError("Unable to load the speaker diarization model.") from None

    if pipeline is None:
        logger.error("Pyannote returned no speaker diarization pipeline.")
        raise RuntimeError("Unable to load the speaker diarization model.")

    try:
        diarization = pipeline(str(path))
        segments: List[DiarizationSegment] = [  # noqa: UP006
            {
                "start": float(turn.start),
                "end": float(turn.end),
                "speaker": str(speaker),
            }
            for turn, _, speaker in diarization.itertracks(yield_label=True)
        ]
    except Exception:  # noqa: BLE001 - normalize failures from third-party inference
        logger.error("Unable to execute Pyannote speaker diarization.")
        raise RuntimeError("Unable to execute speaker diarization.") from None

    segments.sort(key=lambda segment: segment["start"])
    return segments
