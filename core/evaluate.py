"""Evaluasi video terhadap checklist dengan Gemini (transkrip + frame berlabel waktu)."""
from __future__ import annotations

import logging
from typing import Any

from google.genai import types

from .frames import Frame
from .gemini_retry import generate_with_retry
from .schemas import (
    ChecklistTemplate,
    LLMEvaluation,
    LLMItemResult,
    TranscriptSegment,
    Verdict,
)
from .universal_rules import ROLE_LABELS

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"

SYSTEM_INSTRUCTION = """\
Anda adalah reviewer kepatuhan layanan bank yang teliti dan objektif.
Anda menilai video role-play layanan bank (satpam, teller, atau customer service)
berdasarkan checklist yang diberikan.

Aturan penilaian:
1. Nilai SETIAP item checklist, gunakan item_id persis seperti yang diberikan.
2. Dasarkan penilaian hanya pada transkrip dan frame yang diberikan. Jangan berasumsi.
   Transkrip dibuat otomatis oleh mesin (ASR) dan bisa salah menulis kata
   Indonesia, nama bank, atau istilah (mis. "papiri" bisa jadi "BRI"). Jangan
   menghukum petugas karena salah tulis di transkrip. Nilai kefasihan, kesopanan,
   dan slang hanya dari kata yang jelas terbaca. Untuk menyatakan sebuah langkah
   tidak pernah dilakukan, pastikan sudah memeriksa seluruh transkrip dan semua
   frame; jika transkrip terlalu kacau untuk memastikan, gunakan "uncertain".
3. verdict: "pass" jika ada bukti jelas terpenuhi, "fail" jika ada bukti jelas
   tidak terpenuhi atau tidak pernah dilakukan, "uncertain" jika bukti tidak cukup
   (misalnya frame tidak menangkap momen tersebut). Lebih baik "uncertain"
   daripada menebak.
4. confidence: angka 0 sampai 1 yang jujur. Jangan selalu tinggi.
5. moment_sec: detik (angka, bukan teks) yang paling relevan sebagai bukti, supaya
   reviewer bisa langsung melompat ke sana.
   - "pass": detik saat perilaku itu terlihat atau terdengar.
   - "fail" atau "uncertain" pada momen tertentu: detik saat masalah terjadi.
   - Jika langkah TIDAK PERNAH dilakukan di seluruh video, atau tidak ada momen
     spesifik: isi null. Jangan mengarang detik 0.
6. quote: salin persis satu kutipan dari transkrip yang mendukung penilaian, baik
   untuk "pass" maupun "fail". Jangan memparafrase. Untuk "pass" yang didasarkan
   pada ucapan, quote wajib diisi. Jika penilaian murni visual atau tidak ada
   ucapan yang relevan, isi null.
7. reason: satu atau dua kalimat Bahasa Indonesia, merujuk pada bukti yang dilihat.
8. Nilai HANYA perilaku petugas dengan peran yang disebutkan. Langkah yang memang
   menjadi tugas peran lain (misalnya nasabah dirujuk ke bagian lain untuk proses
   berikutnya) bukan kesalahan petugas ini dan jangan dijadikan alasan "fail".
9. moment_sec, quote, dan reason harus mendukung perilaku yang dinilai oleh item
   itu sendiri, bukan perilaku item lain. Contoh: untuk item penutup layanan
   (closing), pilih momen di akhir interaksi saat petugas menawarkan bantuan
   tambahan, bukan momen saat petugas membahas hal lain di tengah video.
10. Untuk aturan tentang akhir video: periksa ucapan dan semua frame di detik-detik
   terakhir (frame di bagian akhir diambil lebih rapat). Ucapan atau tindakan di luar
   skenario setelah closing, misalnya berbicara santai, memakai bahasa daerah, tertawa,
   atau melihat ke kamera, berarti "fail".
11. Nilai item HANYA berdasarkan kalimat deskripsinya. Jangan menambah syarat yang
   tidak tertulis di deskripsi, dan jangan meminjam syarat dari item lain atau dari
   judul skenario. Contoh: item penutup layanan terpenuhi jika petugas menawarkan
   bantuan tambahan, tanpa harus mengarahkan nasabah ke antrean atau bagian lain.
   Jika satu item gagal, itu tidak otomatis membuat item lain gagal; nilai tiap
   item sendiri-sendiri.
12. Bedakan "tidak ada bukti" dari "ada bukti pelanggaran". Gunakan "fail" hanya
   jika ada ucapan atau gambar yang jelas menunjukkan item itu dilanggar, atau
   langkah yang seharusnya terdengar jelas dari ucapan petugas memang tidak pernah
   diucapkan padahal transkripnya jelas. Jika Anda hanya tidak menemukan bukti
   (misalnya item visual tetapi frame tidak menangkapnya, atau langkah mungkin
   terjadi di antara dua frame), gunakan "uncertain", bukan "fail".
"""


def format_transcript(segments: list[TranscriptSegment]) -> str:
    if not segments:
        return "(tidak ada ucapan terdeteksi)"
    return "\n".join(f"[{s.start:.1f}s -> {s.end:.1f}s] {s.text}" for s in segments)


def build_contents(
    template: ChecklistTemplate,
    segments: list[TranscriptSegment],
    frames: list[Frame],
) -> list[Any]:
    """Susun isi prompt. Tiap frame didahului label detiknya, supaya Gemini tahu
    gambar mana terjadi di detik berapa (tanpa label, urutan gambar saja ambigu)."""
    checklist_lines = [
        f"- {i.id} | {i.category} | {i.description} | "
        f"bukti dari: {', '.join(m.value for m in i.modalities)}"
        for i in template.items
        if i.enabled
    ]
    contents: list[Any] = [
        f"Skenario: {template.scenario_title}\n"
        f"Peran petugas yang dinilai: {ROLE_LABELS[template.role]}\n\n"
        "Checklist yang harus dinilai (id | kategori | deskripsi | sumber bukti):\n"
        + "\n".join(checklist_lines),
        "Transkrip ucapan dengan timestamp:\n" + format_transcript(segments),
        "Frame video yang diambil berkala. Label menunjukkan detik ke-berapa:",
    ]
    for f in frames:
        contents.append(f"[Frame detik ke-{f.second}]")
        contents.append(types.Part.from_bytes(data=f.path.read_bytes(), mime_type="image/jpeg"))
    return contents


def reconcile(evaluation: LLMEvaluation, template: ChecklistTemplate) -> list[LLMItemResult]:
    """Pastikan hasil tepat satu per item aktif, urut sesuai template.

    - item yang tidak dikembalikan model -> "uncertain" (wajib dicek manusia)
    - item_id yang tidak dikenal atau duplikat -> dibuang
    """
    wanted = [i.id for i in template.items if i.enabled]
    by_id: dict[str, LLMItemResult] = {}
    for r in evaluation.results:
        if r.item_id in wanted and r.item_id not in by_id:
            by_id[r.item_id] = r
        else:
            log.warning("Hasil %s dibuang (tidak dikenal atau duplikat)", r.item_id)

    out: list[LLMItemResult] = []
    for item_id in wanted:
        out.append(
            by_id.get(item_id)
            or LLMItemResult(
                item_id=item_id,
                verdict=Verdict.UNCERTAIN,
                confidence=0.0,
                reason="AI tidak mengembalikan penilaian untuk item ini; perlu dicek manual.",
            )
        )
    return out


def evaluate(
    client: Any,
    template: ChecklistTemplate,
    segments: list[TranscriptSegment],
    frames: list[Frame],
    *,
    model: str = DEFAULT_MODEL,
    max_attempts: int = 5,
) -> list[LLMItemResult]:
    """Panggil Gemini dengan output terstruktur; ulangi jika gagal atau tidak valid."""
    contents = build_contents(template, segments, frames)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        response_schema=LLMEvaluation,
        temperature=0.0,
    )
    return generate_with_retry(
        client,
        model=model,
        contents=contents,
        config=config,
        parse=lambda text: reconcile(LLMEvaluation.model_validate_json(text), template),
        what="Evaluasi Gemini",
        max_attempts=max_attempts,
    )
