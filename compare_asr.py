"""Bandingkan transkrip ASR (Whisper berbagai ukuran vs Gemini) pada video yang sama.

Contoh (satu baris):
    python compare_asr.py contoh.mp4 --reference output/work/contoh/transcript_large-v3.json --others output/work/contoh/transcript_small.json output/work/contoh/transcript_medium.json

Transkrip Gemini dibuat (atau diambil dari cache) di folder kerja video itu.
Referensi dipakai sebagai pembanding, bukan kebenaran mutlak.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from pathlib import Path

from core.asr_gemini import DEFAULT_ASR_MODEL
from core.schemas import TranscriptSegment
from core.textmetrics import KEYWORDS, align_offsets, count_slang, keyword_hits, wer, words
from core.transcripts import get_transcript, load_segments_file


def label_of(path: Path) -> str:
    return path.stem.removeprefix("transcript_")


def full_text(segments: list[TranscriptSegment]) -> str:
    return " ".join(s.text for s in segments)


def clock(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def build_report(
    sources: dict[str, list[TranscriptSegment]],
    reference: str,
    window: int = 60,
    bucket: int = 10,
) -> str:
    ref = sources[reference]
    ref_text = full_text(ref)
    ref_words = words(ref_text)
    ref_slang_total = sum(count_slang(ref_text).values())
    names = [reference] + [n for n in sources if n != reference]
    colw = max(len(n) for n in names) + 2
    label_w = 44

    def row(label: str, values: list[str]) -> str:
        return f"{label:<{label_w}}" + "".join(f"{v:<{colw}}" for v in values)

    texts = {n: full_text(sources[n]) for n in names}
    hits = {n: keyword_hits(texts[n]) for n in names}
    slang = {n: sum(count_slang(texts[n]).values()) for n in names}

    wer_cells, shift_cells = ["(referensi)"], ["-"]
    for n in names[1:]:
        wer_cells.append(f"{wer(ref_words, words(texts[n])):.2f}")
        diffs = align_offsets(ref, sources[n])
        shift_cells.append(
            f"{statistics.median(diffs):.1f} ({len(diffs)} cocok)" if diffs else "n/a"
        )

    lines = [
        "",
        row("Metrik", names),
        "-" * (label_w + colw * len(names)),
        row("Jumlah kata", [str(len(words(texts[n]))) for n in names]),
        row("WER vs referensi (kecil = mirip)", wer_cells),
        row(
            f"Kata kunci ditemukan (dari {len(KEYWORDS)})",
            [str(sum(hits[n].values())) for n in names],
        ),
        row("Kata slang terdeteksi", [str(slang[n]) for n in names]),
        row("Selisih timestamp median (detik)", shift_cells),
        "",
        "Kata kunci per sumber (ya = ejaan benar ditemukan):",
    ]
    for label in KEYWORDS:
        lines.append(row(f"  {label}", ["ya" if hits[n][label] else "tidak" for n in names]))

    lines += ["", f"Perbandingan {window} detik pertama, per {bucket} detik:"]
    for start in range(0, window, bucket):
        lines.append(f"[{clock(start)}-{clock(start + bucket)}]")
        for n in names:
            chunk = " ".join(s.text for s in sources[n] if start <= s.start < start + bucket)
            lines.append(f"  {n:<{colw}}: {chunk or '(kosong)'}")

    lines += ["", "Catatan:"]
    lines.append(
        "- WER dihitung terhadap referensi yang sendiri bisa salah: ini ukuran "
        "kemiripan, bukan akurasi mutlak. Dengarkan videonya untuk memastikan."
    )
    if ref_slang_total == 0:
        lines.append(
            "- Referensi tidak memuat kata slang, jadi risiko ucapan 'dirapikan' belum "
            "teruji. Uji juga dengan video yang sengaja memakai bahasa tidak baku."
        )
    else:
        for n in names[1:]:
            if slang[n] < ref_slang_total:
                lines.append(
                    f"- PERINGATAN: {n} memuat {slang[n]} kata slang, referensi "
                    f"{ref_slang_total}. Kemungkinan ucapan dirapikan."
                )
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Bandingkan transkrip ASR")
    parser.add_argument("video", type=Path)
    parser.add_argument("--reference", type=Path, required=True,
                        help="File transkrip pembanding, mis. transcript_large-v3.json")
    parser.add_argument("--others", type=Path, nargs="*", default=[],
                        help="File transkrip lain untuk dibandingkan")
    parser.add_argument("--asr-model", default=DEFAULT_ASR_MODEL)
    parser.add_argument("--work-dir", type=Path, default=None,
                        help="Folder kerja video (default: output/work/<nama video>)")
    parser.add_argument("--window", type=int, default=60, help="Detik awal yang ditampilkan")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Set dulu environment variable GEMINI_API_KEY.", file=sys.stderr)
        return 1
    if not args.video.exists():
        print(f"File video tidak ditemukan: {args.video}", file=sys.stderr)
        return 1
    for p in [args.reference, *args.others]:
        if not p.exists():
            print(f"File transkrip tidak ditemukan: {p}", file=sys.stderr)
            return 1

    from google import genai  # diimpor di sini agar --help dan tes tidak butuh library ini

    client = genai.Client(api_key=api_key)
    work = args.work_dir or Path("output/work") / args.video.stem

    ref_label = label_of(args.reference)
    sources = {ref_label: load_segments_file(args.reference)}
    for p in args.others:
        sources[label_of(p)] = load_segments_file(p)
    print("Membuat transkrip Gemini (memakai cache jika ada)...")
    sources[f"gemini_{args.asr_model}"] = get_transcript(
        args.video, work, asr="gemini", client=client, asr_model=args.asr_model
    )

    print(build_report(sources, ref_label, args.window))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
