"""Transkripsi audio dengan faster-whisper.

Audio di-decode langsung oleh ffmpeg ke array numpy 16 kHz mono. Ini menggantikan
langkah wav + librosa di notebook, sekaligus menghindari bug library AV, dan
mengurangi satu dependensi berat untuk image Lambda. Binary `ffmpeg` harus ada.
"""
from __future__ import annotations

import logging
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

from .schemas import TranscriptSegment

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


def extract_audio(video_path: str | Path) -> np.ndarray:
    """Decode audio video menjadi float32 mono 16 kHz."""
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(video_path),
        "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg gagal: {proc.stderr.decode(errors='replace')[:500]}")
    audio = np.frombuffer(proc.stdout, dtype=np.float32)
    if audio.size == 0:
        raise ValueError("Video tidak memiliki track audio")
    return audio


@lru_cache(maxsize=2)
def _load_model(model_size: str, compute_type: str):
    # Import di dalam fungsi: modul lain tetap ringan saat diuji tanpa faster-whisper,
    # dan model hanya dimuat sekali per container Lambda (cache).
    from faster_whisper import WhisperModel

    log.info("Memuat model Whisper '%s' (%s)", model_size, compute_type)
    return WhisperModel(model_size, device="cpu", compute_type=compute_type)


def transcribe(
    video_path: str | Path,
    model_size: str = "base",
    language: str = "id",
    compute_type: str = "int8",
) -> list[TranscriptSegment]:
    """Transkripsi video menjadi segmen bertimestamp.

    language="id" dipaksa supaya Whisper tidak salah mendeteksi bahasa.
    vad_filter menyaring bagian hening agar tidak muncul teks halusinasi.
    """
    audio = extract_audio(video_path)
    model = _load_model(model_size, compute_type)
    segments, _info = model.transcribe(
        audio, language=language, beam_size=5, vad_filter=True
    )
    result = [
        TranscriptSegment(start=s.start, end=s.end, text=s.text.strip())
        for s in segments
        if s.text.strip()
    ]
    log.info("Transkripsi selesai: %d segmen", len(result))
    return result
