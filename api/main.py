"""Rute FastAPI. Logika ada di api/service.py; berkas ini hanya menerjemahkan HTTP."""
from __future__ import annotations

import hmac
import os
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.schemas import ReviewSubmission

from . import service
from .service import BadRequest, Ctx, NotFound

app = FastAPI(title="Video Review API")

# Autentikasi memakai header Authorization (bukan cookie), jadi "*" aman untuk CORS.
_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"]
)


@app.exception_handler(NotFound)
async def _not_found(_, exc: NotFound):
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(BadRequest)
async def _bad_request(_, exc: BadRequest):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@lru_cache
def get_ctx() -> Ctx:
    import boto3

    ddb = boto3.resource("dynamodb")
    return Ctx(
        results=ddb.Table(os.environ["RESULTS_TABLE"]),
        reviews=ddb.Table(os.environ["REVIEWS_TABLE"]),
        templates=ddb.Table(os.environ["TEMPLATES_TABLE"]),
        s3=boto3.client("s3"),
        bucket=os.environ["VIDEO_BUCKET"],
    )


def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("API_TOKEN")
    if not expected:  # gagal tertutup: tanpa token terkonfigurasi, semua ditolak
        raise HTTPException(status_code=500, detail="API_TOKEN belum diset di server")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Token tidak valid")


class UploadRequest(BaseModel):
    filename: str
    role: str
    title: str


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/uploads", dependencies=[Depends(require_token)])
def create_upload(body: UploadRequest, ctx: Ctx = Depends(get_ctx)):
    return service.create_upload(ctx, body.filename, body.role, body.title)


@app.get("/videos", dependencies=[Depends(require_token)])
def list_videos(ctx: Ctx = Depends(get_ctx)):
    return service.list_videos(ctx)


@app.get("/videos/{video_id}", dependencies=[Depends(require_token)])
def get_video(video_id: str, ctx: Ctx = Depends(get_ctx)):
    return service.get_video(ctx, video_id)


@app.put("/videos/{video_id}/review", dependencies=[Depends(require_token)])
def submit_review(video_id: str, body: ReviewSubmission, ctx: Ctx = Depends(get_ctx)):
    return service.submit_review(ctx, video_id, body)


@app.get("/templates/{role}/{scenario_id}", dependencies=[Depends(require_token)])
def get_template(role: str, scenario_id: str, ctx: Ctx = Depends(get_ctx)):
    return service.get_template(ctx, role, scenario_id)
