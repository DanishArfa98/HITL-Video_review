"""Logika API tanpa ketergantungan pada FastAPI (mudah diuji).

Semua akses AWS lewat `Ctx` supaya bisa diganti objek tiruan di tes.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.schemas import ReviewSubmission, Role, slugify
from core.storage import DynamoResultStore, DynamoTemplateStore, from_dynamo, to_dynamo
from core.template_edit import apply_template_edits

UPLOAD_EXPIRES_SEC = 900
VIDEO_EXPIRES_SEC = 3600
MAX_TITLE_LEN = 200


class NotFound(Exception):
    pass


class BadRequest(Exception):
    pass


@dataclass
class Ctx:
    results: Any    # tabel DynamoDB hasil (kunci: video_id)
    reviews: Any    # tabel DynamoDB review manusia (kunci: video_id)
    templates: Any  # tabel DynamoDB template (kunci: template_id)
    s3: Any         # klien boto3 S3
    bucket: str


def _scan_all(table: Any) -> list[dict]:
    items: list[dict] = []
    kwargs: dict = {}
    while True:
        resp = table.scan(**kwargs)
        items += resp.get("Items", [])
        if not resp.get("LastEvaluatedKey"):
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().strip()


# --------------------------------------------------------------------------
def create_upload(
    ctx: Ctx, filename: str, role: str, title: str, now: datetime | None = None
) -> dict:
    """Tautan unggah S3 sementara. Peran dan judul dititipkan sebagai metadata objek,
    yang dibaca Lambda pipeline saat video masuk."""
    if not filename.lower().endswith(".mp4"):
        raise BadRequest("Hanya file .mp4 yang didukung")
    try:
        role_enum = Role(role)
    except ValueError:
        raise BadRequest(f"Peran tidak dikenal: {role!r}") from None
    title_ascii = _ascii(title)
    if not title_ascii:
        raise BadRequest("Judul skenario wajib diisi (huruf latin)")
    if len(title_ascii) > MAX_TITLE_LEN:
        raise BadRequest(f"Judul terlalu panjang (maks {MAX_TITLE_LEN} karakter)")
    try:
        stem = slugify(Path(filename).stem)
    except ValueError:
        raise BadRequest("Nama file tidak valid") from None

    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d%H%M%S")
    unique = f"{stem}-{stamp}"
    key = f"uploads/{unique}.mp4"
    headers = {
        "Content-Type": "video/mp4",
        "x-amz-meta-role": role_enum.value,
        "x-amz-meta-title": title_ascii,
    }
    url = ctx.s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": ctx.bucket,
            "Key": key,
            "ContentType": "video/mp4",
            "Metadata": {"role": role_enum.value, "title": title_ascii},
        },
        ExpiresIn=UPLOAD_EXPIRES_SEC,
    )
    return {
        "video_id": f"vid_{unique}",  # sama dengan yang dibuat Lambda pipeline
        "key": key,
        "upload_url": url,
        "headers": headers,
        "expires_in": UPLOAD_EXPIRES_SEC,
    }


def _review_map(ctx: Ctx) -> dict[str, dict]:
    return {r["video_id"]: r for r in (from_dynamo(i) for i in _scan_all(ctx.reviews))}


def list_videos(ctx: Ctx) -> list[dict]:
    """Daftar ringkas video, terbaru di atas. Status mengikuti keputusan reviewer."""
    reviews = _review_map(ctx)
    rows = []
    for raw in _scan_all(ctx.results):
        r = from_dynamo(raw)
        review = reviews.get(r["video_id"])
        rows.append(
            {
                "video_id": r["video_id"],
                "scenario_id": r["scenario_id"],
                "role": r.get("role"),
                "status": review["final_decision"] if review else r.get("status", "ai_done"),
                "summary": r.get("summary"),
                "processed_at": r["meta"]["processed_at"],
                "duration_sec": r["meta"]["duration_sec"],
            }
        )
    rows.sort(key=lambda x: x["processed_at"], reverse=True)
    return rows


def get_video(ctx: Ctx, video_id: str) -> dict:
    """Hasil AI + keputusan reviewer + template + tautan pemutaran video."""
    result = DynamoResultStore(ctx.results).get(video_id)
    if result is None:
        raise NotFound(f"Video {video_id} tidak ditemukan")

    review_item = ctx.reviews.get_item(Key={"video_id": video_id}).get("Item")
    template = None
    if result.role is not None:
        template = DynamoTemplateStore(ctx.templates).get(result.scenario_id, result.role)

    video_url = None
    if result.source:
        video_url = ctx.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": result.source.bucket, "Key": result.source.key},
            ExpiresIn=VIDEO_EXPIRES_SEC,
        )

    return {
        "result": result.model_dump(mode="json"),
        "review": from_dynamo(review_item) if review_item else None,
        "template": template.model_dump(mode="json") if template else None,
        "video_url": video_url,
    }


def submit_review(ctx: Ctx, video_id: str, submission: ReviewSubmission) -> dict:
    """Simpan keputusan reviewer (override + Approve/Reject) dan terapkan edit checklist."""
    if submission.video_id != video_id:
        raise BadRequest("video_id di body tidak sama dengan di URL")
    result = DynamoResultStore(ctx.results).get(video_id)
    if result is None:
        raise NotFound(f"Video {video_id} tidak ditemukan")

    known = {r.item_id for r in result.results}
    unknown = [o.item_id for o in submission.overrides if o.item_id not in known]
    if unknown:
        raise BadRequest(f"Item tidak ada di hasil video ini: {', '.join(unknown)}")

    new_version = None
    if submission.template_edits:
        if result.role is None:
            raise BadRequest("Video ini tidak punya peran, template tidak bisa diedit")
        store = DynamoTemplateStore(ctx.templates)
        template = store.get(result.scenario_id, result.role)
        if template is None:
            raise NotFound("Template skenario tidak ditemukan")
        try:
            edited = apply_template_edits(template, submission.template_edits)
        except ValueError as e:
            raise BadRequest(str(e)) from None
        store.put(edited)
        new_version = edited.template_version

    # Keputusan manusia disimpan terpisah dari hasil AI supaya pemrosesan ulang
    # video tidak menimpanya.
    item = to_dynamo(submission.model_dump_json())
    item["updated_at"] = datetime.now(timezone.utc).isoformat()
    ctx.reviews.put_item(Item=item)
    return {"video_id": video_id, "status": submission.final_decision,
            "template_version": new_version}


def get_template(ctx: Ctx, role: str, scenario_id: str) -> dict:
    try:
        role_enum = Role(role)
    except ValueError:
        raise BadRequest(f"Peran tidak dikenal: {role!r}") from None
    template = DynamoTemplateStore(ctx.templates).get(scenario_id, role_enum)
    if template is None:
        raise NotFound("Template tidak ditemukan")
    return template.model_dump(mode="json")
