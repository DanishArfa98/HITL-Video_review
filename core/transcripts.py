"""Transkrip video dengan cache: Whisper (lokal) atau Gemini (dari audio).

Whisper di CPU lambat dan Gemini bisa gagal sementara (503), jadi hasil transkrip
disimpan di work/transcript_*.json dan dipakai ulang selama file video yang sama
(ukuran dan waktu ubah) dan konfigurasi yang sama.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .asr_gemini import DEFAULT_ASR_MODEL, asr_config_id, transcribe_gemini
from .audio import transcribe
from .schemas import TranscriptSegment

log = logging.getLogger(__name__)


def load_segments_file(path: str | Path) -> list[TranscriptSegment]:
    """Baca file transkrip: file cache ({"segments": [...]}) atau daftar segmen polos."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data["segments"] if isinstance(data, dict) else data
    return [TranscriptSegment(**s) for s in items]


def get_transcript(
    video_path: str | Path,
    work: str | Path,
    *,
    asr: str = "whisper",
    whisper_size: str = "base",
    client: Any = None,
    asr_model: str = DEFAULT_ASR_MODEL,
) -> list[TranscriptSegment]:
    video_path, work = Path(video_path), Path(work)
    stat = video_path.stat()
    stamp = {"size": stat.st_size, "mtime": int(stat.st_mtime)}

    if asr == "whisper":
        cache, config = work / f"transcript_{whisper_size}.json", "whisper"
    elif asr == "gemini":
        if client is None:
            raise ValueError("ASR Gemini membutuhkan client Gemini")
        cache, config = work / f"transcript_gemini_{asr_model}.json", asr_config_id(asr_model)
    else:
        raise ValueError(f"ASR tidak dikenal: {asr!r}")

    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            # cache Whisper lama tidak punya "config", dianggap "whisper"
            if data.get("video") == stamp and data.get("config", "whisper") == config:
                log.info("Memakai transkrip tersimpan: %s", cache.name)
                return [TranscriptSegment(**s) for s in data["segments"]]
        except (ValueError, KeyError, TypeError, AttributeError):
            log.warning("Cache transkrip rusak, transkripsi ulang")

    if asr == "whisper":
        segments = transcribe(video_path, model_size=whisper_size)
    else:
        segments = transcribe_gemini(client, video_path, model=asr_model)

    work.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(
            {"video": stamp, "config": config, "segments": [s.model_dump() for s in segments]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return segments
