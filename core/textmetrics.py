"""Metrik teks sederhana untuk membandingkan transkrip ASR (tanpa dependensi tambahan)."""
from __future__ import annotations

import re
from collections import Counter

from .schemas import TranscriptSegment

_WORD = re.compile(r"[^\W_]+", re.UNICODE)

# Istilah penting di domain ini. Pencocokan ketat pada ejaan: "custom service"
# dianggap tidak cocok dengan "customer service".
KEYWORDS: dict[str, list[str]] = {
    "BRI": ["bri"],
    "KTP": ["ktp"],
    "NPWP": ["npwp"],
    "NIB": ["nib"],
    "customer service": ["customer service"],
    "rekening": ["rekening"],
    "antrean": ["antrean", "antrian"],
}

SLANG_WORDS = frozenset(
    {
        "gak", "nggak", "ga", "udah", "sih", "dong", "deh", "kok", "banget",
        "gimana", "aja", "nih", "tuh", "bro", "gue", "lu", "lo", "kayak",
        "emang", "yaudah",
    }
)


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def wer(reference: list[str], hypothesis: list[str]) -> float:
    """Word error rate (jarak edit kata dibagi jumlah kata referensi)."""
    if not reference:
        return 0.0 if not hypothesis else 1.0
    prev = list(range(len(hypothesis) + 1))
    for i, r in enumerate(reference, start=1):
        cur = [i]
        for j, h in enumerate(hypothesis, start=1):
            cost = 0 if r == h else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1] / len(reference)


def keyword_hits(text: str) -> dict[str, bool]:
    joined = " " + " ".join(words(text)) + " "
    return {
        label: any(f" {variant} " in joined for variant in variants)
        for label, variants in KEYWORDS.items()
    }


def count_slang(text: str) -> Counter:
    return Counter(w for w in words(text) if w in SLANG_WORDS)


def align_offsets(
    reference: list[TranscriptSegment],
    hypothesis: list[TranscriptSegment],
    max_gap: float = 15.0,
    min_words: int = 3,
    min_overlap: float = 0.6,
) -> list[float]:
    """Selisih waktu mulai (detik) antar segmen yang isinya sama pada dua transkrip.

    Segmen dicocokkan lewat irisan kata (dibagi kata terpendek) supaya tahan
    terhadap perbedaan cara memotong kalimat.
    """
    ref_sets = [(s.start, set(words(s.text))) for s in reference]
    diffs: list[float] = []
    for h in hypothesis:
        hs = set(words(h.text))
        if len(hs) < min_words:
            continue
        best: tuple[float, float] | None = None
        for start, rs in ref_sets:
            if abs(start - h.start) > max_gap or len(rs) < min_words:
                continue
            overlap = len(hs & rs) / min(len(hs), len(rs))
            if overlap >= min_overlap and (best is None or overlap > best[0]):
                best = (overlap, abs(start - h.start))
        if best:
            diffs.append(best[1])
    return diffs
