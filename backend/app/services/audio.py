"""Audio validation and traceable preprocessing without modifying originals."""

from __future__ import annotations

import json
import shutil
import subprocess
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

from .pipeline import ERRORS, PipelineFailure


@dataclass(frozen=True, slots=True)
class AudioMetadata:
    duration_seconds: float
    sample_rate: int
    channels: int
    codec: str
    format_name: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class PreprocessResult:
    source_path: str
    output_path: str
    metadata_before: AudioMetadata
    metadata_after: AudioMetadata
    command: list[str] | None
    copied_without_conversion: bool

    def trace(self) -> dict:
        result = asdict(self)
        result["metadata_before"] = asdict(self.metadata_before)
        result["metadata_after"] = asdict(self.metadata_after)
        return result


def _probe_wav(path: Path) -> AudioMetadata:
    try:
        with wave.open(str(path), "rb") as audio:
            frames = audio.getnframes()
            rate = audio.getframerate()
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
    except (wave.Error, EOFError) as exc:
        raise PipelineFailure(ERRORS["audio_corrupt"], context={"path": path.name}) from exc
    if not rate or not frames:
        raise PipelineFailure(ERRORS["audio_corrupt"], context={"path": path.name})
    return AudioMetadata(
        duration_seconds=frames / rate,
        sample_rate=rate,
        channels=channels,
        codec=f"pcm_s{sample_width * 8}le",
        format_name="wav",
        size_bytes=path.stat().st_size,
    )


def probe_audio(path: Path, *, ffprobe_path: str = "ffprobe") -> AudioMetadata:
    if not path.is_file() or path.stat().st_size == 0:
        raise PipelineFailure(ERRORS["audio_corrupt"], context={"path": path.name})
    wav_error: PipelineFailure | None = None
    if path.suffix.lower() == ".wav":
        try:
            return _probe_wav(path)
        except PipelineFailure as exc:
            # Compressed WAV variants are valid but unsupported by Python's wave module.
            wav_error = exc
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,sample_rate,channels:format=duration,format_name",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        if wav_error:
            raise wav_error from exc
        raise PipelineFailure(ERRORS["unsupported_audio"], context={"path": path.name}) from exc
    if completed.returncode != 0:
        raise PipelineFailure(ERRORS["audio_corrupt"], context={"path": path.name})
    try:
        payload = json.loads(completed.stdout)
        stream = payload["streams"][0]
        format_data = payload["format"]
        return AudioMetadata(
            duration_seconds=float(format_data["duration"]),
            sample_rate=int(stream["sample_rate"]),
            channels=int(stream["channels"]),
            codec=str(stream["codec_name"]),
            format_name=str(format_data["format_name"]),
            size_bytes=path.stat().st_size,
        )
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PipelineFailure(ERRORS["audio_corrupt"], context={"path": path.name}) from exc


def validate_audio(
    path: Path,
    *,
    allowed_extensions: frozenset[str],
    max_bytes: int,
    min_duration_seconds: float,
    ffprobe_path: str = "ffprobe",
) -> AudioMetadata:
    if path.suffix.lower() not in allowed_extensions:
        raise PipelineFailure(ERRORS["unsupported_audio"], context={"extension": path.suffix})
    if not path.is_file() or path.stat().st_size <= 0 or path.stat().st_size > max_bytes:
        raise PipelineFailure(
            ERRORS["audio_corrupt"],
            context={"size": path.stat().st_size if path.exists() else None},
        )
    metadata = probe_audio(path, ffprobe_path=ffprobe_path)
    if metadata.duration_seconds < min_duration_seconds:
        raise PipelineFailure(
            ERRORS["audio_too_short"], context={"duration": metadata.duration_seconds}
        )
    return metadata


def preprocess_audio(
    source: Path,
    output: Path,
    metadata: AudioMetadata,
    *,
    target_sample_rate: int = 16_000,
    ffmpeg_path: str = "ffmpeg",
    ffprobe_path: str = "ffprobe",
    timeout_seconds: int = 600,
) -> PreprocessResult:
    output.parent.mkdir(parents=True, exist_ok=True)
    already_standard = (
        source.suffix.lower() == ".wav"
        and metadata.sample_rate == target_sample_rate
        and metadata.channels == 1
        and metadata.codec in {"pcm_s16le", "pcm_s16be"}
    )
    command: list[str] | None = None
    if already_standard:
        shutil.copy2(source, output)
    else:
        command = [
            ffmpeg_path,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(target_sample_rate),
            "-c:a",
            "pcm_s16le",
            "-af",
            "loudnorm=I=-23:LRA=7:TP=-2",
            str(output),
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout_seconds, check=False
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise PipelineFailure(
                ERRORS["unsupported_audio"], context={"source": source.name}
            ) from exc
        if completed.returncode != 0:
            raise PipelineFailure(ERRORS["audio_corrupt"], context={"source": source.name})
    metadata_after = probe_audio(output, ffprobe_path=ffprobe_path)
    return PreprocessResult(
        str(source), str(output), metadata, metadata_after, command, already_standard
    )
