"""Transkripsi dengan Gemini: audio dikirim langsung, hasilnya segmen bertimestamp.

Pengganti Whisper yang tidak perlu model berat di Lambda. Risiko yang dijaga lewat
prompt: LLM cenderung "merapikan" ucapan (slang jadi baku), sehingga pelanggaran
bahasa tersembunyi. Karena itu prompt meminta transkripsi PERSIS seperti diucapkan.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import wave
from pathlib import Path
from typing import Any

import numpy as np
from google.genai import types
from pydantic import BaseModel

from .audio import SAMPLE_RATE, extract_audio
from .gemini_retry import generate_with_retry
from .schemas import TranscriptSegment

log = logging.getLogger(__name__)

DEFAULT_ASR_MODEL = "gemini-2.5-flash"
MAX_INLINE_BYTES = 18 * 1024 * 1024  # batas kiriman inline Gemini sekitar 20 MB

ASR_PROMPT = """\
Transkripsikan audio percakapan layanan bank di Indonesia (petugas dan nasabah) berikut.

Aturan:
1. Tulis PERSIS apa yang diucapkan, dalam Bahasa Indonesia. JANGAN merapikan,
   membakukan, memperbaiki tata bahasa, atau menerjemahkan. Pertahankan kata tidak
   baku, slang, kata isian ("eh", "hmm", "anu"), pengulangan, dan kalimat yang
   tidak selesai.
2. JANGAN menambahkan kata yang tidak diucapkan dan jangan menebak kalimat yang
   tidak terdengar. Jika sebuah bagian tidak terdengar jelas, tulis [tidak jelas].
3. Istilah yang mungkin muncul; tulis dengan ejaan ini hanya jika memang
   diucapkan: BRI, KTP, NPWP, NIB, customer service, rekening, nasabah, antrean,
   setoran, buku tabungan, kartu debit.
4. Pisahkan menjadi segmen pendek: satu kalimat atau satu giliran bicara,
   sekitar 2 sampai 10 detik.
5. Untuk tiap segmen beri waktu mulai dan selesai dalam format MM:SS (menit:detik,
   mis. 01:05). Waktu harus sesuai posisi sebenarnya di audio, berurutan, dan tidak
   melebihi durasi audio.
6. Abaikan bagian tanpa ucapan (hening atau musik). Jika tidak ada ucapan sama
   sekali, kembalikan daftar kosong.
"""


class _Segment(BaseModel):
    start: str
    end: str
    text: str


class _Transcript(BaseModel):
    segments: list[_Segment]


def asr_config_id(model: str) -> str:
    """Penanda konfigurasi untuk cache: berubah jika model atau prompt berubah."""
    return hashlib.sha1(f"{model}\n{ASR_PROMPT}".encode("utf-8")).hexdigest()[:10]


_CLOCK = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d+))?$")


def parse_clock(value: object) -> float:
    """'01:05' -> 65.0, '1:02:03' -> 3723.0, '00:07.5' -> 7.5, '7s' -> 7.0, 12 -> 12.0."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().removesuffix("s").strip()
    m = _CLOCK.match(text)
    if m:
        hours, minutes, seconds, frac = m.groups()
        total = int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)
        if frac:
            total += float("0." + frac)
        return float(total)
    return float(text)  # mis. "7.5"; ValueError jika tidak dikenali


def pcm_wav_bytes(audio: np.ndarray) -> bytes:
    """float32 mono 16 kHz -> byte file WAV 16-bit."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def segments_from_response(data: _Transcript, duration: float) -> list[TranscriptSegment]:
    """Rapikan keluaran Gemini: urutkan, perbaiki waktu selesai, buang yang tidak valid.

    Timestamp dari LLM tidak selalu konsisten, jadi dijaga di sini: tidak boleh
    melewati durasi audio, `end` harus setelah `start` dan tidak melewati segmen
    berikutnya.
    """
    raw: list[tuple[float, float, str]] = []
    for s in data.segments:
        text = s.text.strip()
        if not text:
            continue
        start = max(0.0, parse_clock(s.start))
        try:
            end = parse_clock(s.end)
        except ValueError:
            end = start
        raw.append((start, end, text))
    raw.sort(key=lambda x: x[0])

    valid = [x for x in raw if x[0] <= duration + 1.0]
    if raw and not valid:
        raise ValueError(
            f"Semua timestamp melebihi durasi audio ({duration:.0f} detik); "
            "kemungkinan format waktu salah"
        )
    if len(valid) < len(raw):
        log.warning("%d segmen di luar durasi audio dibuang", len(raw) - len(valid))

    out: list[TranscriptSegment] = []
    for i, (start, end, text) in enumerate(valid):
        nxt = valid[i + 1][0] if i + 1 < len(valid) else duration
        limit = nxt if nxt > start else duration
        if end <= start:
            end = start + 2.0
        end = min(end, limit, duration)
        if end <= start:
            continue
        out.append(TranscriptSegment(start=round(start, 2), end=round(end, 2), text=text))
    return out


def transcribe_gemini(
    client: Any,
    video_path: str | Path,
    *,
    model: str = DEFAULT_ASR_MODEL,
    max_attempts: int = 5,
) -> list[TranscriptSegment]:
    """Transkripsi audio video dengan Gemini."""
    audio = extract_audio(video_path)
    duration = audio.size / SAMPLE_RATE
    wav = pcm_wav_bytes(audio)
    if len(wav) > MAX_INLINE_BYTES:
        raise ValueError(
            f"Audio {duration:.0f} detik terlalu besar untuk dikirim inline "
            f"({len(wav) / 1e6:.1f} MB, batas {MAX_INLINE_BYTES / 1e6:.0f} MB)"
        )

    contents = [
        types.Part.from_bytes(data=wav, mime_type="audio/wav"),
        f"{ASR_PROMPT}\nDurasi audio: {duration:.0f} detik.",
    ]
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_Transcript,
        temperature=0.0,
    )
    segments = generate_with_retry(
        client,
        model=model,
        contents=contents,
        config=config,
        parse=lambda text: segments_from_response(_Transcript.model_validate_json(text), duration),
        what="Transkripsi Gemini",
        max_attempts=max_attempts,
    )
    log.info("Transkripsi Gemini selesai: %d segmen", len(segments))
    return segments
