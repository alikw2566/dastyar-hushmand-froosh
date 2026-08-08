import struct
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.diarization import MODEL_ID, diarize_audio


@pytest.fixture
def mono_wav(tmp_path: Path) -> Path:
    path = tmp_path / "mono.wav"
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16_000)
        wav_file.writeframes(struct.pack("<h", 0) * 160)
    return path


@pytest.fixture
def stereo_wav(tmp_path: Path) -> Path:
    path = tmp_path / "stereo.wav"
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16_000)
        wav_file.writeframes(struct.pack("<hh", 0, 0) * 160)
    return path


@pytest.mark.parametrize("token", ["", " ", "\t\r\n"])
def test_missing_token_is_rejected(mono_wav: Path, token: str) -> None:
    with pytest.raises(ValueError, match="HuggingFace token is required"):
        diarize_audio(str(mono_wav), token)


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        diarize_audio(str(tmp_path / "missing.wav"), "fake-token")


def test_directory_is_not_accepted_as_audio(tmp_path: Path) -> None:
    directory = tmp_path / "directory.wav"
    directory.mkdir()
    with pytest.raises(FileNotFoundError):
        diarize_audio(str(directory), "fake-token")


def test_non_wav_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "audio.mp3"
    path.write_bytes(b"not-audio")
    with pytest.raises(ValueError, match="Only WAV"):
        diarize_audio(str(path), "fake-token")


def test_corrupt_wav_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.wav"
    path.write_bytes(b"not-a-wav")
    with pytest.raises(ValueError, match="not a valid WAV"):
        diarize_audio(str(path), "fake-token")


def test_stereo_wav_is_rejected(stereo_wav: Path) -> None:
    with pytest.raises(ValueError, match="Expected a mono WAV"):
        diarize_audio(str(stereo_wav), "fake-token")


@patch("app.services.diarization.Pipeline")
def test_pipeline_uses_required_model(pipeline_class: MagicMock, mono_wav: Path) -> None:
    pipeline = MagicMock()
    pipeline.return_value.itertracks.return_value = []
    pipeline_class.from_pretrained.return_value = pipeline

    assert diarize_audio(str(mono_wav), " fake-token ") == []
    pipeline_class.from_pretrained.assert_called_once_with(
        MODEL_ID,
        use_auth_token="fake-token",
    )
    pipeline.assert_called_once_with(str(mono_wav))


@patch("app.services.diarization.Pipeline")
def test_output_is_typed_and_sorted(pipeline_class: MagicMock, mono_wav: Path) -> None:
    late_turn = MagicMock(start=5, end=7.5)
    early_turn = MagicMock(start=0, end=2)
    pipeline = MagicMock()
    pipeline.return_value.itertracks.return_value = [
        (late_turn, None, "SPEAKER_01"),
        (early_turn, None, "SPEAKER_00"),
    ]
    pipeline_class.from_pretrained.return_value = pipeline

    assert diarize_audio(str(mono_wav), "fake-token") == [
        {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
        {"start": 5.0, "end": 7.5, "speaker": "SPEAKER_01"},
    ]


@patch("app.services.diarization.Pipeline")
def test_empty_diarization_is_valid(pipeline_class: MagicMock, mono_wav: Path) -> None:
    pipeline = MagicMock()
    pipeline.return_value.itertracks.return_value = []
    pipeline_class.from_pretrained.return_value = pipeline

    assert diarize_audio(str(mono_wav), "fake-token") == []


@patch("app.services.diarization.Pipeline")
def test_model_load_error_is_safe(pipeline_class: MagicMock, mono_wav: Path) -> None:
    pipeline_class.from_pretrained.side_effect = Exception("secret-token remote detail")

    with pytest.raises(RuntimeError) as raised:
        diarize_audio(str(mono_wav), "secret-token")

    assert str(raised.value) == "Unable to load the speaker diarization model."
    assert "secret-token" not in str(raised.value)


@patch("app.services.diarization.Pipeline")
def test_execution_error_is_safe(pipeline_class: MagicMock, mono_wav: Path) -> None:
    pipeline = MagicMock(side_effect=Exception("secret-token inference detail"))
    pipeline_class.from_pretrained.return_value = pipeline

    with pytest.raises(RuntimeError) as raised:
        diarize_audio(str(mono_wav), "secret-token")

    assert str(raised.value) == "Unable to execute speaker diarization."
    assert "secret-token" not in str(raised.value)
