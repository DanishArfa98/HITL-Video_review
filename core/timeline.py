"""Logika murni tanpa API: timestamp -> rentang, bukti, timeline heatmap, dan ringkasan.

Gemini hanya memberi satu momen (detik) per item. Di sini momen itu diberi padding
(toleransi frame 5 detik), dilengkapi bukti dari Whisper dan nama frame, lalu
digabung menjadi `timeline` yang langsung dibaca player React.
"""
from __future__ import annotations

from .frames import Frame
from .schemas import (
    Evidence,
    FlaggedRange,
    ItemResult,
    LLMItemResult,
    Modality,
    ResultSummary,
    TimelineSegment,
    TimelineState,
    TranscriptSegment,
    Verdict,
)

PAD_SEC = 5.0
_EPS = 1e-6
_PRIORITY = {TimelineState.CLEAR: 0, TimelineState.UNCERTAIN: 1, TimelineState.FLAGGED: 2}


def padded_range(
    timestamp: float, duration: float, padding: float = PAD_SEC
) -> tuple[float, float] | None:
    """Timestamp titik -> rentang [t-padding, t+padding], dipotong ke batas video."""
    start = max(0.0, timestamp - padding)
    end = min(duration, timestamp + padding)
    if end - start <= _EPS:
        return None
    return round(start, 3), round(end, 3)


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _quote_segments(quote: str | None, segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Cocokkan kutipan dari Gemini ke segmen Whisper asli (bukan parafrase LLM)."""
    if not quote:
        return []
    q = _norm(quote)
    if len(q) < 8:
        return []
    matched = []
    for s in segments:
        n = _norm(s.text)
        if len(n) >= 8 and (q in n or n in q):
            matched.append(s)
    return matched


def build_item_result(
    r: LLMItemResult,
    segments: list[TranscriptSegment],
    frames: list[Frame],
    duration: float,
    padding: float = PAD_SEC,
    modalities: list[Modality] | None = None,
) -> ItemResult:
    """Ubah penilaian mentah Gemini menjadi ItemResult lengkap.

    - Bukti (kutipan Whisper + nama frame) dilampirkan untuk SEMUA verdict yang
      punya momen, termasuk pass, supaya reviewer bisa memverifikasi dengan cepat.
    - `flagged_ranges` (yang mewarnai heatmap) hanya dibuat untuk fail/uncertain.
    - Momen di luar durasi video dianggap tidak valid dan diabaikan.
    """
    moment = r.moment_sec if r.moment_sec is not None and r.moment_sec <= duration else None
    rng = padded_range(moment, duration, padding) if moment is not None else None

    in_window: list[TranscriptSegment] = []
    frame_files: list[str] = []
    if rng:
        start, end = rng
        in_window = [s for s in segments if s.end > start and s.start < end]
        frame_files = [f.filename for f in frames if start <= f.second <= end]

    # Bukti hanya dari sumber yang relevan: aturan visual tidak perlu kutipan ucapan,
    # aturan audio tidak perlu frame. modalities=None berarti semua sumber dipakai.
    use_transcript = modalities is None or Modality.AUDIO in modalities
    use_frames = modalities is None or Modality.VISION in modalities
    if not use_frames:
        frame_files = []
    seg_list: list[TranscriptSegment] = []
    if use_transcript:
        matched = _quote_segments(r.quote, segments)
        unique = {(s.start, s.end, s.text): s for s in in_window + matched}
        seg_list = sorted(unique.values(), key=lambda s: s.start)

    flagged: list[FlaggedRange] = []
    if rng and r.verdict != Verdict.PASS:
        if seg_list and frame_files:
            source = "transcript+frame"
        elif seg_list:
            source = "transcript"
        elif frame_files or use_frames:
            source = "frame"
        else:
            source = "transcript"
        flagged = [FlaggedRange(start=rng[0], end=rng[1], source=source)]

    return ItemResult(
        item_id=r.item_id,
        verdict=r.verdict,
        confidence=r.confidence,
        reason=r.reason,
        moment_sec=moment,
        evidence=Evidence(transcript=seg_list, frames=frame_files),
        flagged_ranges=flagged,
    )


def build_timeline(results: list[ItemResult], duration: float) -> list[TimelineSegment]:
    """Susun segmen berurutan yang menutupi seluruh video: clear / uncertain / flagged.

    Rentang yang tumpang tindih dipecah di setiap titik batas. Pada tiap potongan,
    state tertinggi menang (flagged > uncertain > clear). Potongan bersebelahan
    dengan state dan item yang sama digabung.
    """
    if duration <= _EPS:
        return []

    intervals: list[tuple[float, float, TimelineState, str]] = []
    for r in results:
        if r.verdict == Verdict.PASS:
            continue
        state = TimelineState.FLAGGED if r.verdict == Verdict.FAIL else TimelineState.UNCERTAIN
        for fr in r.flagged_ranges:
            start, end = max(0.0, fr.start), min(duration, fr.end)
            if end - start > _EPS:
                intervals.append((start, end, state, r.item_id))

    points = {0.0, round(duration, 3)}
    for start, end, _, _ in intervals:
        points.add(round(start, 3))
        points.add(round(end, 3))
    pts = sorted(points)

    segments: list[TimelineSegment] = []
    for a, b in zip(pts, pts[1:]):
        if b - a <= _EPS:
            continue
        covering = [iv for iv in intervals if iv[0] < b and iv[1] > a]
        if covering:
            state = max((iv[2] for iv in covering), key=lambda s: _PRIORITY[s])
            item_ids = sorted({iv[3] for iv in covering if iv[2] == state})
        else:
            state, item_ids = TimelineState.CLEAR, []

        if segments and segments[-1].state == state and segments[-1].item_ids == item_ids:
            segments[-1].end = b
        else:
            segments.append(TimelineSegment(start=a, end=b, state=state, item_ids=item_ids))

    return segments


def build_summary(results: list[ItemResult]) -> ResultSummary:
    """Ringkasan hasil, termasuk item bermasalah yang tidak terlihat di timeline."""
    failed = sum(1 for r in results if r.verdict == Verdict.FAIL)
    uncertain = sum(1 for r in results if r.verdict == Verdict.UNCERTAIN)
    passed = sum(1 for r in results if r.verdict == Verdict.PASS)
    unlocated = [
        r.item_id for r in results if r.verdict != Verdict.PASS and not r.flagged_ranges
    ]
    return ResultSummary(
        total=len(results),
        passed=passed,
        failed=failed,
        uncertain=uncertain,
        unlocated_item_ids=unlocated,
        needs_attention=bool(failed or uncertain),
    )
