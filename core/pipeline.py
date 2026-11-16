"""Perangkai pipeline pre-screening: video + template -> PrescreenResult."""
from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .asr_gemini import DEFAULT_ASR_MODEL
from .evaluate import DEFAULT_MODEL, evaluate
from .frames import extract_frames
from .schemas import ChecklistTemplate, PrescreenResult, ProcessingMeta
from .timeline import PAD_SEC, build_item_result, build_summary, build_timeline
from .transcripts import get_transcript

log = logging.getLogger(__name__)


def run_prescreen(
    video_path: str | Path,
    template: ChecklistTemplate,
    client: Any,
    *,
    video_id: str | None = None,
    work_dir: str | Path | None = None,
    asr: str = "whisper",
    whisper_size: str = "base",
    asr_model: str = DEFAULT_ASR_MODEL,
    frame_interval: int = 5,
    llm_model: str = DEFAULT_MODEL,
    padding: float = PAD_SEC,
) -> PrescreenResult:
    """Jalankan seluruh pre-screening untuk satu video.

    asr: "whisper" (lokal) atau "gemini" (transkrip dari audio lewat Gemini).
    Di Lambda, work_dir sebaiknya di bawah /tmp. Jika tidak diberikan, dibuat
    folder sementara (tanpa cache antar-proses).
    """
    video_path = Path(video_path)
    work = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="video_review_"))
    video_id = video_id or f"vid_{datetime.now():%Y%m%d_%H%M%S}"

    log.info("[1/4] Transkripsi audio (%s)", asr)
    segments = get_transcript(
        video_path, work, asr=asr, whisper_size=whisper_size, client=client, asr_model=asr_model
    )

    log.info("[2/4] Ekstraksi frame tiap %ds", frame_interval)
    frames, duration = extract_frames(video_path, work / "frames", interval_sec=frame_interval)

    log.info("[3/4] Evaluasi Gemini (%d frame)", len(frames))
    llm_results = evaluate(client, template, segments, frames, model=llm_model)

    log.info("[4/4] Menyusun hasil dan timeline")
    modalities = {i.id: i.modalities for i in template.items}
    item_results = [
        build_item_result(r, segments, frames, duration, padding, modalities.get(r.item_id))
        for r in llm_results
    ]
    timeline = build_timeline(item_results, duration)

    asr_label = f"faster-whisper-{whisper_size}" if asr == "whisper" else f"{asr_model} (audio)"
    return PrescreenResult(
        video_id=video_id,
        scenario_id=template.scenario_id,
        role=template.role,
        template_version=template.template_version,
        meta=ProcessingMeta(
            duration_sec=duration,
            frame_interval_sec=frame_interval,
            models={"asr": asr_label, "llm": llm_model},
            processed_at=datetime.now(timezone.utc),
        ),
        results=item_results,
        timeline=timeline,
        summary=build_summary(item_results),
    )
