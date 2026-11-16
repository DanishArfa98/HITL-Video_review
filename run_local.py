"""Jalankan pipeline pre-screening secara lokal pada satu video.

Contoh:
    export GEMINI_API_KEY="isi-api-key-anda"
    python run_local.py video.mp4 "Satpam melayani nasabah rekening perusahaan" --role satpam

Template checklist disimpan di templates/<peran>_<scenario_id>.json dan dipakai ulang
untuk video berikutnya dengan peran dan judul skenario yang sama (meniru DynamoDB).
Template boleh disunting manual (mis. "enabled": false) lalu dijalankan ulang.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from google import genai
from google.genai import types

from core.pipeline import run_prescreen
from core.schemas import Role, Verdict
from core.template_store import load_or_create_template

ICONS = {Verdict.PASS: "[ OK ]", Verdict.FAIL: "[FAIL]", Verdict.UNCERTAIN: "[ ?? ]"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-screening video review (lokal)")
    parser.add_argument("video", type=Path, help="Path file video .mp4")
    parser.add_argument("title", help='Judul skenario, mis. "Satpam melayani nasabah ..."')
    parser.add_argument("--role", required=True, choices=[r.value for r in Role],
                        help="Peran petugas yang tampil di video")
    parser.add_argument("--whisper-model", default="base", help="base | small | medium")
    parser.add_argument("--asr", choices=["whisper", "gemini"], default="whisper",
                        help="Sumber transkrip: whisper (lokal) atau gemini (dari audio)")
    parser.add_argument("--asr-model", default="gemini-2.5-flash",
                        help="Model Gemini untuk transkripsi (dipakai jika --asr gemini)")
    parser.add_argument("--frame-interval", type=int, default=5)
    parser.add_argument("--llm-model", default="gemini-2.5-flash",
                        help="Ganti jika model utama sedang sibuk (503)")
    parser.add_argument("--out-dir", type=Path, default=Path("output"))
    parser.add_argument("--templates-dir", type=Path, default=Path("templates"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Set dulu environment variable GEMINI_API_KEY.", file=sys.stderr)
        return 1
    if not args.video.exists():
        print(f"File video tidak ditemukan: {args.video}", file=sys.stderr)
        return 1

    role = Role(args.role)
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(api_version="v1beta"))
    template = load_or_create_template(client, args.title, role, args.templates_dir)

    result = run_prescreen(
        args.video,
        template,
        client,
        asr=args.asr,
        asr_model=args.asr_model,
        whisper_size=args.whisper_model,
        frame_interval=args.frame_interval,
        llm_model=args.llm_model,
        work_dir=args.out_dir / "work" / args.video.stem,  # satu folder kerja per video
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"{result.video_id}.json"
    out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    descriptions = {i.id: i.description for i in template.items}
    print(f"\nHasil untuk {args.video.name} ({result.meta.duration_sec:.0f} detik), peran: {role.value}")
    for r in result.results:
        print(f"{ICONS[r.verdict]} {r.item_id} (conf {r.confidence:.2f}) {descriptions[r.item_id]}")
        if r.moment_sec is not None:
            quote = r.evidence.transcript[0].text if r.evidence.transcript else ""
            print(f"         bukti di sekitar {r.moment_sec:.0f}s {('| ' + quote) if quote else ''}")
        for fr in r.flagged_ranges:
            print(f"         -> cek {fr.start:.0f}s sampai {fr.end:.0f}s: {r.reason}")
        if r.verdict != Verdict.PASS and not r.flagged_ranges:
            print(f"         -> tidak ada momen spesifik (periksa manual): {r.reason}")

    s = result.summary
    if s:
        print(f"\nRingkasan: {s.passed} pass, {s.failed} fail, {s.uncertain} uncertain")
        if s.unlocated_item_ids:
            print(
                "PERHATIAN: item berikut bermasalah tapi tidak punya momen waktu, "
                f"jadi tidak tampak di timeline: {', '.join(s.unlocated_item_ids)}"
            )
    print(f"\nJSON lengkap: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
