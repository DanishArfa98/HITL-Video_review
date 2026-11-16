"""Entry point AWS Lambda: video baru di S3 -> pre-screening -> hasil JSON.

Event yang didukung:
  1. Notifikasi S3 langsung (Records[].s3)
  2. Pesan SQS yang isinya notifikasi S3 (Records[].body)
  3. Event uji manual:
       {"bucket": "...", "key": "...", "role": "satpam", "title": "..."}
       {"local_video": "/data/contoh.mp4", "role": "satpam", "title": "..."}

Untuk event S3, peran dan judul skenario dibaca dari metadata objek
(x-amz-meta-role dan x-amz-meta-title), yang diisi saat video diunggah.

Variabel lingkungan:
  GEMINI_API_KEY   wajib
  TEMPLATES_DIR    folder template (default /tmp/templates)
  RESULT_DIR       folder hasil JSON (default /tmp/results)
  TEMPLATES_TABLE  opsional; nama tabel DynamoDB untuk template (jika kosong: file)
  RESULTS_TABLE    opsional; nama tabel DynamoDB untuk hasil
  RESULT_BUCKET    opsional; jika diisi, hasil juga diunggah ke S3
  RESULT_PREFIX    awalan key hasil di S3 (default "results/")
  LLM_MODEL, ASR_MODEL  opsional; default gemini-2.5-flash
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote_plus

from core.pipeline import run_prescreen
from core.schemas import Role, VideoSource, slugify
from core.storage import DynamoResultStore, DynamoTemplateStore
from core.template_store import load_or_create_template

log = logging.getLogger()
log.setLevel(logging.INFO)


@dataclass
class Job:
    bucket: str | None = None
    key: str | None = None
    local_video: str | None = None
    role: str | None = None
    title: str | None = None
    message_id: str | None = None  # untuk laporan kegagalan SQS

    @property
    def name(self) -> str:
        return Path(self.local_video or self.key or "video").stem


def _s3_records(records: list[dict], message_id: str | None = None) -> list[Job]:
    jobs = []
    for rec in records:
        s3 = rec.get("s3")
        if not s3:
            continue
        jobs.append(
            Job(
                bucket=s3["bucket"]["name"],
                key=unquote_plus(s3["object"]["key"]),
                message_id=message_id,
            )
        )
    return jobs


def parse_event(event: dict) -> tuple[list[Job], bool]:
    """Kembalikan (daftar job, apakah event berasal dari SQS)."""
    records = event.get("Records")
    if records:
        if records[0].get("eventSource") == "aws:sqs":
            jobs: list[Job] = []
            for rec in records:
                body = json.loads(rec["body"])
                jobs += _s3_records(body.get("Records", []), rec.get("messageId"))
            return jobs, True
        return _s3_records(records), False
    if event.get("local_video") or (event.get("bucket") and event.get("key")):
        return [
            Job(
                bucket=event.get("bucket"),
                key=event.get("key"),
                local_video=event.get("local_video"),
                role=event.get("role"),
                title=event.get("title"),
            )
        ], False
    raise ValueError("Format event tidak dikenali")


def _default_s3():
    import boto3  # sudah ada di image Lambda

    return boto3.client("s3")


def _default_client():
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY belum diset")
    # JSON mode (response_schema) hanya ada di v1beta; versi SDK terbaru bisa
    # memakai v1 secara bawaan, jadi dikunci eksplisit.
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(api_version="v1beta"))


def _dynamo_table(name: str):
    import boto3

    return boto3.resource("dynamodb").Table(name)


def _template_source(templates_dir: Path):
    name = os.environ.get("TEMPLATES_TABLE")
    return DynamoTemplateStore(_dynamo_table(name)) if name else templates_dir


def process_job(job: Job, *, client: Any, s3: Callable[[], Any] | None = None) -> dict:
    results_dir = Path(os.environ.get("RESULT_DIR", "/tmp/results"))
    templates_dir = Path(os.environ.get("TEMPLATES_DIR", "/tmp/templates"))
    work = Path(os.environ.get("WORK_DIR", "/tmp/work")) / slugify(job.name)
    work.mkdir(parents=True, exist_ok=True)

    try:
        if job.local_video:
            video_path = Path(job.local_video)
        else:
            s3c = (s3 or _default_s3)()
            head = s3c.head_object(Bucket=job.bucket, Key=job.key)
            meta = head.get("Metadata", {})
            job.role = job.role or meta.get("role")
            job.title = job.title or meta.get("title")
            video_path = work / Path(job.key).name
            s3c.download_file(job.bucket, job.key, str(video_path))

        if not job.role or not job.title:
            raise ValueError(
                "Peran dan judul skenario wajib ada (metadata S3 'role' dan 'title')"
            )
        role = Role(job.role)
        template = load_or_create_template(client, job.title, role, _template_source(templates_dir))

        result = run_prescreen(
            video_path,
            template,
            client,
            asr="gemini",
            asr_model=os.environ.get("ASR_MODEL", "gemini-2.5-flash"),
            llm_model=os.environ.get("LLM_MODEL", "gemini-2.5-flash"),
            video_id=f"vid_{slugify(job.name)}",
            work_dir=work,
        )

        if job.bucket and job.key:
            result.source = VideoSource(bucket=job.bucket, key=job.key)

        results_dir.mkdir(parents=True, exist_ok=True)
        out_path = results_dir / f"{result.video_id}.json"
        body = result.model_dump_json(indent=2)
        out_path.write_text(body, encoding="utf-8")

        table_name = os.environ.get("RESULTS_TABLE")
        if table_name:
            DynamoResultStore(_dynamo_table(table_name)).put(result)

        result_key = None
        bucket = os.environ.get("RESULT_BUCKET")
        if bucket:
            result_key = f"{os.environ.get('RESULT_PREFIX', 'results/')}{result.video_id}.json"
            (s3 or _default_s3)().put_object(
                Bucket=bucket, Key=result_key, Body=body.encode("utf-8"),
                ContentType="application/json",
            )

        summary = result.summary
        return {
            "video_id": result.video_id,
            "needs_attention": bool(summary and summary.needs_attention),
            "passed": summary.passed if summary else None,
            "failed": summary.failed if summary else None,
            "uncertain": summary.uncertain if summary else None,
            "result_file": str(out_path),
            "result_key": result_key,
        }
    finally:
        # Folder kerja (video, frame) dibersihkan supaya /tmp Lambda tidak penuh
        # pada pemanggilan berikutnya di container yang sama.
        shutil.rmtree(work, ignore_errors=True)


def handler(event: dict, context: Any = None, *, client: Any = None, s3: Callable[[], Any] | None = None) -> dict:
    jobs, from_sqs = parse_event(event)
    client = client or _default_client()

    processed, failures = [], []
    for job in jobs:
        try:
            processed.append(process_job(job, client=client, s3=s3))
        except Exception as exc:  # satu video gagal tidak boleh menggagalkan yang lain
            log.exception("Gagal memproses %s", job.key or job.local_video)
            failures.append({"video": job.key or job.local_video, "error": str(exc),
                             "message_id": job.message_id})

    response: dict = {"processed": processed, "failed": failures}
    if from_sqs:
        # Hanya pesan yang gagal yang dikembalikan ke antrean (partial batch response).
        response["batchItemFailures"] = [
            {"itemIdentifier": f["message_id"]} for f in failures if f["message_id"]
        ]
    return response
