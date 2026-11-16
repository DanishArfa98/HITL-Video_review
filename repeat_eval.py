"""Ukur kestabilan evaluasi: jalankan evaluasi Gemini berulang pada transkrip dan
frame yang SAMA, lalu tampilkan item mana yang verdict-nya berubah antar-run.

Contoh:
    python repeat_eval.py contoh.mp4 "Satpam melayani nasabah yang ingin membuka rekening perusahaan" --role satpam --runs 3

Memakai transkrip tersimpan di output/work/<nama video> (dibuat oleh run_local.py
--asr gemini); jika belum ada, dibuat sekali lalu dipakai untuk semua pengulangan.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter
from pathlib import Path

from google import genai
from google.genai import types

from core.evaluate import evaluate
from core.frames import extract_frames
from core.schemas import Role
from core.template_store import load_or_create_template
from core.transcripts import get_transcript


def summarize(runs: list[dict[str, str]]) -> list[tuple[str, Counter, bool]]:
    """runs: daftar {item_id: verdict}. Kembalikan (item_id, hitungan, stabil?)."""
    items = list(runs[0])
    rows = []
    for item_id in items:
        counts = Counter(r.get(item_id, "hilang") for r in runs)
        rows.append((item_id, counts, len(counts) == 1))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Uji kestabilan evaluasi Gemini")
    ap.add_argument("video", type=Path)
    ap.add_argument("title")
    ap.add_argument("--role", required=True, choices=[r.value for r in Role])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--asr-model", default="gemini-2.5-flash")
    ap.add_argument("--llm-model", default="gemini-2.5-flash")
    ap.add_argument("--out-dir", type=Path, default=Path("output"))
    ap.add_argument("--templates-dir", type=Path, default=Path("templates"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("Set dulu GEMINI_API_KEY.", file=sys.stderr)
        return 1
    client = genai.Client(api_key=key, http_options=types.HttpOptions(api_version="v1beta"))

    role = Role(args.role)
    template = load_or_create_template(client, args.title, role, args.templates_dir)
    work = args.out_dir / "work" / args.video.stem
    segments = get_transcript(args.video, work, asr="gemini", client=client, asr_model=args.asr_model)
    frames, _ = extract_frames(args.video, work / "frames")

    runs = []
    for n in range(1, args.runs + 1):
        print(f"Evaluasi ke-{n}/{args.runs}...")
        res = evaluate(client, template, segments, frames, model=args.llm_model)
        runs.append({r.item_id: r.verdict.value for r in res})

    print("\nItem        hasil tiap run")
    unstable = 0
    for item_id, counts, stable in summarize(runs):
        label = ", ".join(f"{v} x{c}" for v, c in counts.items())
        print(f"{item_id:<10}  {'STABIL ' if stable else 'BERUBAH'}  {label}")
        unstable += 0 if stable else 1
    print(f"\n{unstable} dari {len(runs[0])} item berubah antar-run (transkrip dan frame sama).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
